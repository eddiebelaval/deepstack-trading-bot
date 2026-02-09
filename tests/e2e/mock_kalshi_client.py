"""
Mock Kalshi Client — In-Memory Exchange Simulator

Replaces AuthenticatedKalshiClient entirely. Tracks balance, orders,
positions, and fills in memory. No real API calls.

Features:
    - add_market() / update_price() for test setup
    - auto_fill toggle (immediate vs resting orders)
    - _fail_next_n_requests knob for circuit breaker tests
    - Full interface parity with AuthenticatedKalshiClient
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class MockKalshiClient:
    """
    In-memory exchange simulator matching AuthenticatedKalshiClient interface.

    Tracks balance, orders, positions, and fills without any real API calls.
    """

    def __init__(
        self,
        initial_balance_cents: int = 25000,
        auto_fill: bool = True,
    ):
        self.balance_cents = initial_balance_cents
        self.portfolio_value_cents = 0
        self.auto_fill = auto_fill

        # State tracking
        self._markets: Dict[str, Dict[str, Any]] = {}
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._positions: Dict[str, Dict[str, Any]] = {}  # ticker -> position
        self._fills: List[Dict[str, Any]] = []

        # Failure injection
        self._fail_next_n_requests = 0
        self._request_count = 0

        # Connection state
        self._connected = False

    # -----------------------------------------------------------------
    # Test Setup Methods (not part of real client interface)
    # -----------------------------------------------------------------

    def add_market(
        self,
        ticker: str,
        title: str = "Test Market",
        yes_bid: int = 48,
        yes_ask: int = 52,
        no_bid: int = 48,
        no_ask: int = 52,
        volume: int = 1000,
        status: str = "open",
        series_ticker: Optional[str] = None,
        last_price: Optional[int] = None,
    ) -> None:
        """Add a market to the simulated exchange."""
        self._markets[ticker] = {
            "ticker": ticker,
            "title": title,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
            "last_price": last_price or ((yes_bid + yes_ask) // 2),
            "volume": volume,
            "volume_24h": volume,
            "open_interest": volume // 2,
            "status": status,
            "close_time": "2026-12-31T00:00:00Z",
            "expiration_time": "2026-12-31T00:00:00Z",
            "series_ticker": series_ticker,
        }

    def update_price(
        self,
        ticker: str,
        yes_bid: Optional[int] = None,
        yes_ask: Optional[int] = None,
        no_bid: Optional[int] = None,
        no_ask: Optional[int] = None,
    ) -> None:
        """Update a market's prices (simulates price movement)."""
        if ticker not in self._markets:
            raise ValueError(f"Market {ticker} not found")

        market = self._markets[ticker]
        if yes_bid is not None:
            market["yes_bid"] = yes_bid
        if yes_ask is not None:
            market["yes_ask"] = yes_ask
        if no_bid is not None:
            market["no_bid"] = no_bid
        if no_ask is not None:
            market["no_ask"] = no_ask
        market["last_price"] = (market["yes_bid"] + market["yes_ask"]) // 2

    def set_fail_next(self, n: int) -> None:
        """Make the next N requests fail (for circuit breaker testing)."""
        self._fail_next_n_requests = n

    # -----------------------------------------------------------------
    # AuthenticatedKalshiClient Interface
    # -----------------------------------------------------------------

    async def connect(self) -> None:
        """Simulate connection (always succeeds)."""
        self._connected = True

    async def disconnect(self) -> None:
        """Simulate disconnection."""
        self._connected = False

    async def get_balance(self) -> Dict[str, float]:
        """Get simulated account balance."""
        self._check_failure()
        return {
            "balance": self.balance_cents / 100,
            "available": self.balance_cents / 100,
            "portfolio_value": self.portfolio_value_cents / 100,
        }

    async def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        self._check_failure()
        positions = []
        for ticker, pos in self._positions.items():
            if pos.get("quantity", 0) != 0:
                positions.append({
                    "ticker": ticker,
                    "market_ticker": ticker,
                    "position": pos["quantity"] if pos["side"] == "yes" else -pos["quantity"],
                    "resting_orders_count": 0,
                    "total_traded": abs(pos["quantity"]),
                    "realized_pnl": pos.get("realized_pnl", 0) / 100,
                })
        return positions

    async def get_markets(
        self,
        series_ticker: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
    ) -> List[Dict]:
        """Get markets, optionally filtered by series."""
        self._check_failure()
        result = []
        for ticker, market in self._markets.items():
            if market["status"] != status:
                continue
            if series_ticker and market.get("series_ticker") != series_ticker:
                continue
            result.append(dict(market))
            if len(result) >= limit:
                break
        return result

    async def get_market(self, ticker: str) -> Dict:
        """Get single market by ticker."""
        self._check_failure()
        if ticker not in self._markets:
            from kalshi_trader.exceptions import MarketNotFoundError
            raise MarketNotFoundError(ticker)
        return dict(self._markets[ticker])

    async def get_orderbook(self, ticker: str) -> Dict:
        """Get simulated orderbook."""
        self._check_failure()
        market = self._markets.get(ticker, {})
        return {
            "yes": [{"price": market.get("yes_bid", 50), "quantity": 100}],
            "no": [{"price": market.get("no_bid", 50), "quantity": 100}],
        }

    async def create_limit_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        client_order_id: Optional[str] = None,
    ) -> Dict:
        """Create a limit order. Optionally auto-fills immediately."""
        self._check_failure()

        order_id = client_order_id or f"mock-{uuid.uuid4().hex[:8]}"

        order = {
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "remaining_count": count,
            "price": price_cents,
            "status": "resting",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

        self._orders[order_id] = order

        if self.auto_fill:
            self._fill_order(order_id)

        return dict(order)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        self._check_failure()
        if order_id in self._orders:
            order = self._orders[order_id]
            if order["status"] == "resting":
                order["status"] = "canceled"
                return True
        return False

    async def get_order(self, order_id: str) -> Dict:
        """Get order details."""
        self._check_failure()
        if order_id not in self._orders:
            return {}
        return dict(self._orders[order_id])

    async def get_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """Get all orders, optionally filtered."""
        self._check_failure()
        result = []
        for order in self._orders.values():
            if ticker and order["ticker"] != ticker:
                continue
            if status and order["status"] != status:
                continue
            result.append(dict(order))
        return result

    async def cancel_all_orders(self, ticker: Optional[str] = None) -> int:
        """Cancel all resting orders."""
        cancelled = 0
        for order_id, order in self._orders.items():
            if order["status"] != "resting":
                continue
            if ticker and order["ticker"] != ticker:
                continue
            order["status"] = "canceled"
            cancelled += 1
        return cancelled

    # -----------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------

    def _fill_order(self, order_id: str) -> None:
        """Immediately fill an order, updating positions and balance."""
        order = self._orders.get(order_id)
        if not order or order["status"] != "resting":
            return

        ticker = order["ticker"]
        side = order["side"]
        action = order["action"]
        count = order["count"]
        price = order["price"]

        # Update order status
        order["status"] = "executed"
        order["remaining_count"] = 0

        # Record fill
        self._fills.append({
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "price": price,
            "filled_at": datetime.now(timezone.utc).isoformat(),
        })

        # Update balance and positions
        cost_cents = price * count

        if action == "buy":
            self.balance_cents -= cost_cents
            # Update position
            if ticker not in self._positions:
                self._positions[ticker] = {
                    "side": side,
                    "quantity": 0,
                    "avg_price": 0,
                    "realized_pnl": 0,
                }
            pos = self._positions[ticker]
            pos["quantity"] += count
            pos["side"] = side
            pos["avg_price"] = price
            self.portfolio_value_cents += cost_cents

        elif action == "sell":
            self.balance_cents += cost_cents
            if ticker in self._positions:
                pos = self._positions[ticker]
                pnl = (price - pos.get("avg_price", price)) * count
                pos["realized_pnl"] = pos.get("realized_pnl", 0) + pnl
                pos["quantity"] -= count
                self.portfolio_value_cents -= pos.get("avg_price", price) * count
                if pos["quantity"] <= 0:
                    del self._positions[ticker]

    def _check_failure(self) -> None:
        """Check if this request should fail (for testing)."""
        self._request_count += 1
        if self._fail_next_n_requests > 0:
            self._fail_next_n_requests -= 1
            from kalshi_trader.exceptions import KalshiTradingError
            raise KalshiTradingError(
                "Simulated API failure",
                details={"simulated": True},
            )
