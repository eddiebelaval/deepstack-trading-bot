"""
Interactive Brokers Market Adapter

Implements the Market ABC for stock trading via IB TWS/Gateway.
Uses ib_insync for async IB API communication.

Design:
    - Prices normalized to cents at ingress (multiply by 100)
    - Watchlist maps to 'series' parameter from Market ABC
    - Side accepts both "buy"/"sell" (stocks) and "yes"/"no" (legacy)
    - Circuit breaker wraps connection for resilience
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import Market
from .ibkr_types import StockPosition

logger = logging.getLogger(__name__)


class IBKRMarket(Market):
    """
    Interactive Brokers market adapter.

    Connects to IB TWS or Gateway via ib_insync.
    Paper trading: port 7497. Live trading: port 7496.

    Example:
        >>> market = IBKRMarket({"port": 7497, "watchlist": ["SPY", "AAPL"]})
        >>> await market.connect()
        >>> positions = await market.get_positions()
        >>> await market.disconnect()
    """

    def __init__(self, config: Dict[str, Any], client: Any = None):
        super().__init__(config, client)
        self._ib = None  # ib_insync.IB instance
        self._connected = False
        self._host = config.get("host", "127.0.0.1")
        self._port = config.get("port", 7497)  # Paper by default
        self._client_id = config.get("client_id", 1)
        self._account = config.get("account", "")
        self._watchlist = config.get(
            "watchlist", ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
        )
        self._circuit_breaker = None

    @property
    def name(self) -> str:
        return "ibkr"

    async def connect(self) -> bool:
        """
        Connect to IB TWS/Gateway.

        Returns:
            True if connection succeeded, False otherwise.
        """
        try:
            from ib_insync import IB
            from kalshi_trader.circuit_breaker import CircuitBreaker

            self._circuit_breaker = CircuitBreaker(
                name="ibkr_connection",
                failure_threshold=3,
                timeout_seconds=60.0,
            )

            self._ib = IB()
            await self._ib.connectAsync(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=15,
            )
            self._connected = True

            if self._account:
                self._ib.managedAccounts()

            logger.info(
                f"IBKR connected: {self._host}:{self._port} "
                f"(client_id={self._client_id})"
            )
            return True

        except ImportError:
            logger.error(
                "ib_insync not installed. Run: pip install ib_insync"
            )
            return False
        except Exception as e:
            logger.error(f"IBKR connection failed: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from IB TWS/Gateway."""
        if self._ib and self._connected:
            self._ib.disconnect()
            self._connected = False
            logger.info("IBKR disconnected")

    def _ensure_connected(self) -> None:
        """Raise ConnectionError if not connected to IB."""
        if not self._ib or not self._connected:
            raise ConnectionError(
                "IBKR not connected. Call connect() first."
            )

    def _price_to_cents(self, price: float) -> int:
        """Convert dollar price to cents (integer)."""
        return int(round(price * 100))

    def _cents_to_price(self, cents: int) -> float:
        """Convert cents (integer) to dollar price (float)."""
        return cents / 100.0

    async def get_open_markets(
        self,
        series: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
    ) -> List[Dict]:
        """
        Fetch quotes for watchlist symbols (or a single symbol via series).

        The 'series' parameter maps to a single stock symbol for IBKR.
        If not provided, returns quotes for the entire watchlist.

        Args:
            series: Single stock symbol to query, or None for full watchlist
            status: Ignored for stocks (always "open" during market hours)
            limit: Maximum symbols to return

        Returns:
            List of normalized market dicts compatible with the Market ABC.
        """
        self._ensure_connected()
        from ib_insync import Stock

        symbols = self._watchlist if not series else [series]
        markets = []

        for symbol in symbols[:limit]:
            try:
                contract = Stock(symbol, "SMART", "USD")
                self._ib.qualifyContracts(contract)
                ticker = self._ib.reqMktData(contract, snapshot=True)
                await asyncio.sleep(0.5)  # Allow data to arrive

                markets.append(
                    {
                        "ticker": symbol,
                        "title": f"{symbol} Stock",
                        "yes_bid": self._price_to_cents(ticker.bid or 0),
                        "yes_ask": self._price_to_cents(ticker.ask or 0),
                        "no_bid": 0,
                        "no_ask": 0,
                        "last_price": self._price_to_cents(
                            ticker.last or ticker.close or 0
                        ),
                        "volume": int(ticker.volume or 0),
                        "volume_24h": int(ticker.volume or 0),
                        "open_interest": 0,
                        "close_time": None,
                        "expiration_time": None,
                        "status": "open",
                        "asset_class": "stock",
                        "exchange": "SMART",
                    }
                )

                self._ib.cancelMktData(contract)

            except Exception as e:
                logger.warning(f"Failed to fetch quote for {symbol}: {e}")

        return markets

    async def get_market(self, ticker: str) -> Dict:
        """
        Get a single stock quote by symbol.

        Args:
            ticker: Stock symbol (e.g., "AAPL")

        Returns:
            Normalized market dict.

        Raises:
            ValueError: If no data available for the symbol.
        """
        markets = await self.get_open_markets(series=ticker, limit=1)
        if not markets:
            raise ValueError(f"No data for {ticker}")
        return markets[0]

    async def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        order_type: str = "limit",
    ) -> Dict:
        """
        Place a stock order via IB.

        For stocks, 'action' determines direction (buy/sell).
        Legacy prediction market sides (yes/no) are mapped:
            yes -> BUY, no -> SELL.

        Args:
            ticker: Stock symbol
            side: "buy"/"sell" for stocks, or "yes"/"no" (legacy)
            action: "buy" or "sell"
            count: Number of shares
            price_cents: Limit price in cents
            order_type: "limit" (default) or "market"

        Returns:
            Order details dict.
        """
        self._ensure_connected()
        from ib_insync import LimitOrder, MarketOrder, Stock

        # Map side: stocks use buy/sell, prediction markets use yes/no
        # For stocks: action determines direction
        ib_action = action.upper()
        if side in ("yes", "no"):
            # Legacy prediction market side mapping
            ib_action = "BUY" if side == "yes" else "SELL"

        contract = Stock(ticker, "SMART", "USD")
        self._ib.qualifyContracts(contract)

        price = self._cents_to_price(price_cents)

        if order_type == "market":
            order = MarketOrder(ib_action, count)
        else:
            order = LimitOrder(ib_action, count, price)

        trade = self._ib.placeOrder(contract, order)
        await asyncio.sleep(0.1)

        return {
            "order_id": str(trade.order.orderId),
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "price": price_cents,
            "status": trade.orderStatus.status,
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open IB order by order ID.

        Args:
            order_id: The IB order ID (as string).

        Returns:
            True if the order was found and cancelled, False otherwise.
        """
        self._ensure_connected()

        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == order_id:
                self._ib.cancelOrder(trade.order)
                return True
        return False

    async def get_positions(self) -> List[Dict]:
        """
        Get all stock positions with current market data.

        Returns:
            List of position dicts in the normalized Market ABC format.
            Side is mapped: positive qty -> "yes", negative -> "no".
        """
        self._ensure_connected()

        positions = []
        for pos in self._ib.positions():
            contract = pos.contract
            avg_cost = pos.avgCost  # IB returns per-share cost
            qty = int(pos.position)

            if qty == 0:
                continue

            # Request current price
            current_price = avg_cost  # Fallback
            try:
                ticker = self._ib.reqMktData(contract, snapshot=True)
                await asyncio.sleep(0.3)
                if ticker.last and ticker.last > 0:
                    current_price = ticker.last
                elif ticker.close and ticker.close > 0:
                    current_price = ticker.close
                self._ib.cancelMktData(contract)
            except Exception:
                pass

            market_value = qty * current_price
            unrealized_pnl = (current_price - avg_cost) * qty

            positions.append(
                {
                    "ticker": contract.symbol,
                    "position": qty,
                    "contracts": abs(qty),
                    "side": "yes" if qty > 0 else "no",
                    "avg_cost_cents": self._price_to_cents(avg_cost),
                    "current_price_cents": self._price_to_cents(current_price),
                    "market_value_cents": self._price_to_cents(market_value),
                    "unrealized_pnl_cents": self._price_to_cents(
                        unrealized_pnl
                    ),
                    "realized_pnl": 0,
                    "resting_orders_count": 0,
                    "asset_class": "stock",
                    "exchange": contract.exchange or "SMART",
                }
            )

        return positions

    async def get_balance(self) -> Dict[str, float]:
        """
        Get account balance from IB.

        Returns:
            Dict with balance, available funds, and portfolio value.
        """
        self._ensure_connected()

        summary = self._ib.accountSummary()
        result = {
            "balance": 0.0,
            "available": 0.0,
            "portfolio_value": 0.0,
        }

        for item in summary:
            if item.tag == "NetLiquidation":
                result["balance"] = float(item.value)
            elif item.tag == "AvailableFunds":
                result["available"] = float(item.value)
            elif item.tag == "GrossPositionValue":
                result["portfolio_value"] = float(item.value)

        return result

    async def get_enriched_positions(self) -> List[StockPosition]:
        """
        Get positions as StockPosition dataclasses with cost basis tracking.

        Returns:
            List of StockPosition objects with computed cost basis
            and return percentage.
        """
        raw = await self.get_positions()
        return [
            StockPosition(
                symbol=p["ticker"],
                qty=p["contracts"],
                avg_cost_cents=p["avg_cost_cents"],
                current_price_cents=p["current_price_cents"],
                market_value_cents=p["market_value_cents"],
                unrealized_pnl_cents=p["unrealized_pnl_cents"],
                exchange=p.get("exchange", "SMART"),
            )
            for p in raw
        ]

    async def cancel_all_orders(self, ticker: Optional[str] = None) -> int:
        """
        Cancel all open orders, optionally filtered by symbol.

        Args:
            ticker: If provided, only cancel orders for this symbol.

        Returns:
            Number of orders cancelled.
        """
        self._ensure_connected()
        cancelled = 0
        for trade in self._ib.openTrades():
            if ticker and trade.contract.symbol != ticker:
                continue
            self._ib.cancelOrder(trade.order)
            cancelled += 1
        return cancelled

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"IBKRMarket(port={self._port}, {status})"
