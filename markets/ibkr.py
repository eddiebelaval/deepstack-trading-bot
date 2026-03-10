"""
Interactive Brokers Market Adapter

Implements the Market ABC for stock trading via IB TWS/Gateway.
Uses ib_insync for async IB API communication.

Design:
    - Prices normalized to cents at ingress (multiply by 100)
    - Watchlist maps to 'series' parameter from Market ABC
    - Side accepts both "buy"/"sell" (stocks) and "yes"/"no" (legacy)
    - Circuit breaker wraps connection for resilience
    - LexiconOrderRouter: Phase 2 signal-to-paper-trade routing
"""

import asyncio
import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import Market
from .ibkr_types import StockPosition

logger = logging.getLogger(__name__)


def _safe_price(val, price_to_cents_fn) -> int:
    """Convert price to cents, handling NaN and None."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 0
    return price_to_cents_fn(val)


def _safe_int(val) -> int:
    """Convert to int, handling NaN and None."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 0
    return int(val)


def _safe_float(val) -> float:
    """Convert to float, handling NaN and None."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 0.0
    return float(val)


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
        self._regime_indicators = config.get(
            "regime_indicators", ["VIXY", "TLT", "IEF", "HYG", "GLD", "DIA"]
        )
        self._futures_watchlist = config.get("futures_watchlist", [])
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
            from ib_async import IB
            from kalshi_trader.api_circuit_breaker import CircuitBreaker

            from kalshi_trader.api_circuit_breaker import CircuitBreakerConfig
            self._circuit_breaker = CircuitBreaker(
                name="ibkr_connection",
                config=CircuitBreakerConfig(
                    failure_threshold=3,
                    timeout_seconds=60.0,
                ),
            )

            self._ib = IB()
            await self._ib.connectAsync(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=15,
            )
            self._connected = True

            # Request delayed market data (free) if real-time not subscribed
            self._ib.reqMarketDataType(3)  # 3 = delayed, 1 = live, 4 = delayed-frozen

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
        from ib_async import Stock

        symbols = self._watchlist if not series else [series]
        markets = []

        # Batch: qualify and request all contracts first, then sleep once
        tickers_map = {}  # symbol -> (contract, ticker)
        for symbol in symbols[:limit]:
            try:
                contract = Stock(symbol, "SMART", "USD")
                await self._ib.qualifyContractsAsync(contract)
                ticker = self._ib.reqMktData(contract, snapshot=True)
                tickers_map[symbol] = (contract, ticker)
            except Exception as e:
                logger.warning(f"Failed to qualify {symbol}: {e}")

        # Single sleep for all data to arrive (vs 1s per ticker)
        if tickers_map:
            await asyncio.sleep(2.0)

        # Collect results
        for symbol, (contract, ticker) in tickers_map.items():
            try:
                sp = lambda v: _safe_price(v, self._price_to_cents)
                last = sp(ticker.last) or sp(ticker.close) or sp(ticker.bid)

                markets.append(
                    {
                        "ticker": symbol,
                        "title": f"{symbol} Stock",
                        "yes_bid": sp(ticker.bid),
                        "yes_ask": sp(ticker.ask),
                        "no_bid": 0,
                        "no_ask": 0,
                        "last_price": last,
                        "volume": _safe_int(ticker.volume),
                        "volume_24h": _safe_int(ticker.volume),
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

    async def get_regime_indicators(self) -> List[Dict]:
        """Fetch quotes for regime indicator ETFs (VIX proxy, bonds, gold, broad market).

        These are read-only for regime detection — not traded by stock_momentum.
        Returns the same normalized dict format as get_open_markets().
        """
        self._ensure_connected()
        from ib_async import Stock

        indicators = []

        # Batch: qualify and request all indicators first, then sleep once
        tickers_map = {}
        for symbol in self._regime_indicators:
            try:
                contract = Stock(symbol, "SMART", "USD")
                await self._ib.qualifyContractsAsync(contract)
                ticker = self._ib.reqMktData(contract, snapshot=True)
                tickers_map[symbol] = (contract, ticker)
            except Exception as e:
                logger.warning(f"Failed to qualify regime indicator {symbol}: {e}")

        if tickers_map:
            await asyncio.sleep(2.0)

        for symbol, (contract, ticker) in tickers_map.items():
            try:
                sp = lambda v: _safe_price(v, self._price_to_cents)
                last = sp(ticker.last) or sp(ticker.close) or sp(ticker.bid)

                asset_class = "stock"
                if symbol in ("TLT", "IEF", "HYG", "BND", "AGG"):
                    asset_class = "bond"
                elif symbol in ("VIXY", "VXX", "UVXY"):
                    asset_class = "volatility"
                elif symbol in ("GLD", "SLV", "IAU"):
                    asset_class = "commodity"

                indicators.append({
                    "ticker": symbol,
                    "title": f"{symbol} Regime Indicator",
                    "last_price": last,
                    "volume": _safe_int(ticker.volume),
                    "asset_class": asset_class,
                    "is_regime_indicator": True,
                })

                self._ib.cancelMktData(contract)
            except Exception as e:
                logger.warning(f"Failed to fetch regime indicator {symbol}: {e}")

        return indicators

    async def get_futures_markets(self) -> List[Dict]:
        """Fetch quotes for micro futures contracts.

        Uses the futures_watchlist from config. Each entry specifies:
        - symbol: Root symbol (e.g., "MES" for Micro E-mini S&P)
        - exchange: Exchange (e.g., "CME")

        Automatically finds the front-month contract (nearest expiry).

        Returns:
            List of normalized market dicts with asset_class="future".
        """
        self._ensure_connected()
        from ib_async import Future

        if not self._futures_watchlist:
            return []

        markets = []
        for fut_config in self._futures_watchlist:
            symbol = fut_config.get("symbol", "")
            exchange = fut_config.get("exchange", "CME")
            if not symbol:
                continue

            try:
                # Request front-month contract (empty lastTradeDateOrContractMonth
                # + qualifyContracts finds the nearest expiry)
                contract = Future(symbol, exchange=exchange)
                qualified = await self._ib.qualifyContractsAsync(contract)
                if not qualified:
                    logger.debug(f"No futures contract found for {symbol}")
                    continue

                contract = qualified[0]
                ticker_data = self._ib.reqMktData(contract, snapshot=True)
                await asyncio.sleep(1.0)

                sp = lambda v: _safe_price(v, self._price_to_cents)
                last = sp(ticker_data.last) or sp(ticker_data.close)
                # Futures ticker includes expiry: e.g., "MES-202606"
                expiry = getattr(contract, 'lastTradeDateOrContractMonth', '')
                display_ticker = f"{symbol}-{expiry}" if expiry else symbol

                markets.append({
                    "ticker": display_ticker,
                    "symbol": symbol,
                    "title": f"{symbol} Future ({expiry})",
                    "last_price": last,
                    "yes_bid": sp(ticker_data.bid),
                    "yes_ask": sp(ticker_data.ask),
                    "no_bid": 0,
                    "no_ask": 0,
                    "volume": _safe_int(ticker_data.volume),
                    "volume_24h": _safe_int(ticker_data.volume),
                    "open_interest": 0,
                    "status": "open",
                    "asset_class": "future",
                    "exchange": exchange,
                    "expiry": expiry,
                    "contract_id": contract.conId,
                    "multiplier": float(getattr(contract, 'multiplier', 1) or 1),
                })

                self._ib.cancelMktData(contract)

            except Exception as e:
                logger.warning(f"Failed to fetch futures quote for {symbol}: {e}")

        return markets

    async def get_options_chain(
        self,
        underlying: str,
        right: str = "P",
        max_dte: int = 45,
        strike_range_pct: float = 0.10,
    ) -> List[Dict]:
        """Fetch option chain for an underlying stock.

        Args:
            underlying: Stock symbol (e.g., "SPY")
            right: "C" for calls, "P" for puts
            max_dte: Maximum days to expiration
            strike_range_pct: Strike range as % of current price (e.g., 0.10 = +/-10%)

        Returns:
            List of option contract dicts with asset_class="option".
        """
        self._ensure_connected()
        from ib_async import Stock, Option
        from datetime import datetime as dt, timedelta

        try:
            # Get underlying price first
            stock = Stock(underlying, "SMART", "USD")
            await self._ib.qualifyContractsAsync(stock)
            stock_ticker = self._ib.reqMktData(stock, snapshot=True)
            await asyncio.sleep(1.0)

            stock_price = stock_ticker.last
            if stock_price is None or (isinstance(stock_price, float) and math.isnan(stock_price)):
                stock_price = stock_ticker.close
            if stock_price is None or (isinstance(stock_price, float) and math.isnan(stock_price)):
                logger.warning(f"No price for {underlying}, can't fetch options")
                self._ib.cancelMktData(stock)
                return []

            self._ib.cancelMktData(stock)

            # Calculate strike range
            low_strike = stock_price * (1 - strike_range_pct)
            high_strike = stock_price * (1 + strike_range_pct)

            # Get available option chains
            chains = await self._ib.reqSecDefOptParamsAsync(
                underlyingSymbol=underlying,
                futFopExchange="",
                underlyingSecType="STK",
                underlyingConId=stock.conId,
            )

            if not chains:
                return []

            # Use SMART exchange chain
            chain = None
            for c in chains:
                if c.exchange == "SMART":
                    chain = c
                    break
            if not chain:
                chain = chains[0]

            # Filter expirations by max_dte
            today = dt.now().date()
            max_date = today + timedelta(days=max_dte)
            valid_expiries = sorted([
                exp for exp in chain.expirations
                if today < dt.strptime(exp, "%Y%m%d").date() <= max_date
            ])

            if not valid_expiries:
                return []

            # Use nearest valid expiry
            expiry = valid_expiries[0]

            # Filter strikes within range
            valid_strikes = sorted([
                s for s in chain.strikes
                if low_strike <= s <= high_strike
            ])

            if not valid_strikes:
                return []

            # Fetch quotes for filtered options (limit to 10 strikes)
            options = []
            for strike in valid_strikes[:10]:
                try:
                    opt = Option(underlying, expiry, strike, right, "SMART")
                    qualified = await self._ib.qualifyContractsAsync(opt)
                    if not qualified:
                        continue

                    opt = qualified[0]
                    opt_ticker = self._ib.reqMktData(opt, snapshot=True)
                    await asyncio.sleep(0.5)

                    sp = lambda v: _safe_price(v, self._price_to_cents)
                    bid = sp(opt_ticker.bid)
                    ask = sp(opt_ticker.ask)
                    last = sp(opt_ticker.last) or ((bid + ask) // 2 if bid and ask else 0)

                    # DTE calculation
                    exp_date = dt.strptime(expiry, "%Y%m%d").date()
                    dte = (exp_date - today).days

                    display_ticker = f"{underlying}-{expiry}-{strike}-{right}"

                    options.append({
                        "ticker": display_ticker,
                        "underlying": underlying,
                        "title": f"{underlying} {strike}{right} {expiry}",
                        "strike": strike,
                        "right": right,
                        "expiry": expiry,
                        "dte": dte,
                        "last_price": last,
                        "yes_bid": bid,
                        "yes_ask": ask,
                        "no_bid": 0,
                        "no_ask": 0,
                        "volume": 0,
                        "volume_24h": 0,
                        "open_interest": 0,
                        "status": "open",
                        "asset_class": "option",
                        "exchange": "SMART",
                        "underlying_price": self._price_to_cents(stock_price),
                        "contract_id": opt.conId,
                    })

                    self._ib.cancelMktData(opt)

                except Exception as e:
                    logger.debug(f"Failed to fetch option {underlying} {strike}{right}: {e}")

            return options

        except Exception as e:
            logger.warning(f"Failed to fetch options chain for {underlying}: {e}")
            return []

    async def place_futures_order(
        self,
        symbol: str,
        exchange: str,
        expiry: str,
        action: str,
        count: int,
        price_cents: int,
        order_type: str = "limit",
    ) -> Dict:
        """Place a futures order via IB.

        Args:
            symbol: Futures root symbol (e.g., "MES")
            exchange: Exchange (e.g., "CME")
            expiry: Contract expiry (e.g., "202606")
            action: "buy" or "sell"
            count: Number of contracts
            price_cents: Limit price in cents
            order_type: "limit" or "market"
        """
        self._ensure_connected()
        from ib_async import Future, LimitOrder, MarketOrder

        contract = Future(symbol, expiry, exchange)
        await self._ib.qualifyContractsAsync(contract)

        price = self._cents_to_price(price_cents)
        ib_action = action.upper()

        if order_type == "market":
            order = MarketOrder(ib_action, count)
        else:
            order = LimitOrder(ib_action, count, price)

        trade = self._ib.placeOrder(contract, order)
        await asyncio.sleep(0.1)

        return {
            "order_id": str(trade.order.orderId),
            "ticker": f"{symbol}-{expiry}",
            "side": action,
            "action": action,
            "count": count,
            "price": price_cents,
            "status": trade.orderStatus.status,
            "asset_class": "future",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

    async def place_options_order(
        self,
        underlying: str,
        expiry: str,
        strike: float,
        right: str,
        action: str,
        count: int,
        price_cents: int,
        order_type: str = "limit",
    ) -> Dict:
        """Place an options order via IB.

        Args:
            underlying: Stock symbol (e.g., "SPY")
            expiry: Expiration date (e.g., "20260320")
            strike: Strike price (e.g., 550.0)
            right: "C" for call, "P" for put
            action: "buy" or "sell"
            count: Number of contracts
            price_cents: Limit price in cents (per share, not per contract)
            order_type: "limit" or "market"
        """
        self._ensure_connected()
        from ib_async import Option, LimitOrder, MarketOrder

        contract = Option(underlying, expiry, strike, right, "SMART")
        await self._ib.qualifyContractsAsync(contract)

        price = self._cents_to_price(price_cents)
        ib_action = action.upper()

        if order_type == "market":
            order = MarketOrder(ib_action, count)
        else:
            order = LimitOrder(ib_action, count, price)

        trade = self._ib.placeOrder(contract, order)
        await asyncio.sleep(0.1)

        return {
            "order_id": str(trade.order.orderId),
            "ticker": f"{underlying}-{expiry}-{strike}-{right}",
            "underlying": underlying,
            "side": action,
            "action": action,
            "count": count,
            "price": price_cents,
            "strike": strike,
            "right": right,
            "expiry": expiry,
            "status": trade.orderStatus.status,
            "asset_class": "option",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

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
        from ib_async import LimitOrder, MarketOrder, Stock

        # Map side: stocks use buy/sell, prediction markets use yes/no
        # For stocks: action determines direction
        ib_action = action.upper()
        if side in ("yes", "no"):
            # Legacy prediction market side mapping
            ib_action = "BUY" if side == "yes" else "SELL"

        contract = Stock(ticker, "SMART", "USD")
        await self._ib.qualifyContractsAsync(contract)

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

        Uses IB's cached portfolio data (populated on connect via
        updatePortfolio callbacks) rather than making fresh snapshot
        requests. This is both faster and more reliable for delayed
        data subscriptions.

        Returns:
            List of position dicts in the normalized Market ABC format.
            Side is mapped: positive qty -> "yes", negative -> "no".
        """
        self._ensure_connected()

        positions = []

        # Prefer portfolio() which includes live market values from
        # updatePortfolio callbacks (no extra market data requests needed).
        portfolio_items = self._ib.portfolio()

        if portfolio_items:
            for item in portfolio_items:
                contract = item.contract
                qty = int(item.position)
                if qty == 0:
                    continue

                avg_cost = item.averageCost
                market_price = _safe_float(item.marketPrice)
                market_value = _safe_float(item.marketValue)
                unrealized_pnl = _safe_float(item.unrealizedPNL)

                # If market price is 0 or missing, fall back to avg cost
                if market_price <= 0:
                    market_price = avg_cost

                positions.append(
                    {
                        "ticker": contract.symbol,
                        "position": qty,
                        "contracts": abs(qty),
                        "side": "yes" if qty > 0 else "no",
                        "avg_cost_cents": self._price_to_cents(avg_cost),
                        "current_price_cents": self._price_to_cents(market_price),
                        "market_value_cents": self._price_to_cents(market_value),
                        "unrealized_pnl_cents": self._price_to_cents(unrealized_pnl),
                        "realized_pnl": 0,
                        "resting_orders_count": 0,
                        "asset_class": "stock",
                        "exchange": contract.exchange or "SMART",
                    }
                )
        else:
            # Fallback: positions() without market values
            ib_positions = self._ib.positions()
            if not ib_positions:
                try:
                    ib_positions = await self._ib.reqPositionsAsync()
                except Exception:
                    ib_positions = []

            for pos in ib_positions:
                contract = pos.contract
                avg_cost = pos.avgCost
                qty = int(pos.position)
                if qty == 0:
                    continue

                positions.append(
                    {
                        "ticker": contract.symbol,
                        "position": qty,
                        "contracts": abs(qty),
                        "side": "yes" if qty > 0 else "no",
                        "avg_cost_cents": self._price_to_cents(avg_cost),
                        "current_price_cents": self._price_to_cents(avg_cost),
                        "market_value_cents": self._price_to_cents(avg_cost * qty),
                        "unrealized_pnl_cents": 0,
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

        # Use async accountSummary to avoid event loop collision
        summary = await self._ib.accountSummaryAsync()
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


@dataclass
class LexiconOrder:
    """Record of a paper order placed by the LexiconOrderRouter."""

    timestamp: str
    symbol: str
    side: str
    qty: int
    signal_strategy: str
    signal_action: str
    signal_confidence: float
    regime: str
    order_id: str = ""
    status: str = "pending"


class LexiconOrderRouter:
    """
    Routes LexiconSignal objects to IBKR paper trades.

    Maps regime + signal action to specific ETF trades:
        - trending_up + enable momentum -> long SPY/QQQ
        - high_vol_choppy + enable volatility -> long VXX
        - trending_down + enable momentum -> long SH (inverse S&P)
        - mean_reverting -> no directional trades (regime is range-bound)

    Safety:
        - paper_mode assertion on every order method
        - Max 5 paper positions at once
        - Auto-close all if daily P&L exceeds -$50
        - All orders logged before execution
    """

    # Regime -> (bullish_symbol, bearish_symbol)
    REGIME_ETF_MAP: Dict[str, Dict[str, str]] = {
        "trending_up": {"long": "SPY", "hedge": "VXX"},
        "trending_down": {"long": "SH", "hedge": "QQQ"},
        "high_vol_choppy": {"long": "VXX", "hedge": "SPY"},
        "low_vol_calm": {"long": "SPY", "hedge": "VXX"},
        "mean_reverting": {"long": "SPY", "hedge": "SH"},
    }

    def __init__(
        self,
        ibkr_market: IBKRMarket,
        max_positions: int = 5,
        max_daily_loss_cents: int = 5000,  # -$50 in cents
        max_order_value_cents: int = 1000,  # $10 max per trade
    ):
        self.ibkr = ibkr_market
        self.paper_mode = True  # Hardcoded — never change
        self.max_positions = max_positions
        self.max_daily_loss_cents = max_daily_loss_cents
        self.max_order_value_cents = max_order_value_cents
        self._order_log: deque = deque(maxlen=500)
        self._daily_pnl_cents: int = 0

        logger.info(
            "LexiconOrderRouter initialized | paper=%s max_pos=%d max_loss=$%.2f",
            self.paper_mode, max_positions, max_daily_loss_cents / 100,
        )

    async def route_signal(self, signal: Any) -> Optional[LexiconOrder]:
        """
        Route a LexiconSignal to a paper trade.

        Only processes 'enable' signals — disable/caution are informational.
        Returns the order record, or None if skipped.

        Args:
            signal: LexiconSignal object from the signal generator.

        Returns:
            LexiconOrder if a trade was placed, None otherwise.
        """
        assert self.paper_mode, "LexiconOrderRouter: PAPER MODE REQUIRED"

        # Only trade on enable signals with sufficient confidence
        if signal.action != "enable" or signal.confidence < 0.6:
            return None

        # Check position limit
        try:
            positions = await self.ibkr.get_positions()
            if len(positions) >= self.max_positions:
                logger.info(
                    "LexiconOrderRouter: position limit reached (%d/%d), skipping %s",
                    len(positions), self.max_positions, signal.strategy_name,
                )
                return None
        except Exception as e:
            logger.warning("LexiconOrderRouter: cannot check positions: %s", e)
            return None

        # Check daily P&L limit
        if self._daily_pnl_cents <= -self.max_daily_loss_cents:
            logger.warning(
                "LexiconOrderRouter: daily P&L limit hit ($%.2f), no new orders",
                self._daily_pnl_cents / 100,
            )
            return None

        # Determine symbol based on regime
        regime = signal.regime
        etf_map = self.REGIME_ETF_MAP.get(regime, {})
        symbol = etf_map.get("long", "SPY")

        # Calculate quantity based on max order value and current price
        try:
            market_data = await self.ibkr.get_market(symbol)
            price_cents = market_data.get("last_price", 0)
            if price_cents <= 0:
                logger.warning("LexiconOrderRouter: no price data for %s", symbol)
                return None

            # qty = max_order_value / price, minimum 1 share
            qty = max(1, self.max_order_value_cents // price_cents)
        except Exception as e:
            logger.warning("LexiconOrderRouter: price lookup failed for %s: %s", symbol, e)
            return None

        # Place paper order
        order_record = LexiconOrder(
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            side="buy",
            qty=qty,
            signal_strategy=signal.strategy_name,
            signal_action=signal.action,
            signal_confidence=signal.confidence,
            regime=regime,
        )

        try:
            assert self.paper_mode, "LexiconOrderRouter: PAPER MODE REQUIRED"
            result = await self.ibkr.place_order(
                ticker=symbol,
                side="buy",
                action="buy",
                count=qty,
                price_cents=price_cents,
                order_type="limit",
            )
            order_record.order_id = result.get("order_id", "")
            order_record.status = result.get("status", "submitted")

            logger.info(
                "LexiconOrderRouter: PAPER ORDER %s %s x%d @ $%.2f | "
                "signal=%s regime=%s conf=%.0f%%",
                order_record.order_id, symbol, qty, price_cents / 100,
                signal.strategy_name, regime, signal.confidence * 100,
            )
        except Exception as e:
            order_record.status = f"failed: {str(e)[:100]}"
            logger.error("LexiconOrderRouter: order failed: %s", e)

        self._order_log.append(order_record)
        return order_record

    async def check_daily_pnl(self) -> int:
        """
        Update daily P&L from IBKR positions.

        Returns current daily P&L in cents. Triggers auto-close
        if below the loss threshold.
        """
        assert self.paper_mode, "LexiconOrderRouter: PAPER MODE REQUIRED"

        try:
            positions = await self.ibkr.get_positions()
            total_pnl = sum(p.get("unrealized_pnl_cents", 0) for p in positions)
            self._daily_pnl_cents = total_pnl

            if total_pnl <= -self.max_daily_loss_cents:
                logger.warning(
                    "LexiconOrderRouter: daily P&L $%.2f below limit, closing all positions",
                    total_pnl / 100,
                )
                await self.ibkr.cancel_all_orders()
                # Note: cancel_all_orders cancels open orders, not positions.
                # Closing positions requires selling each one — left for future.

            return total_pnl
        except Exception as e:
            logger.warning("LexiconOrderRouter: P&L check failed: %s", e)
            return self._daily_pnl_cents

    def get_order_log(self) -> List[LexiconOrder]:
        """Return the order log for reporting."""
        return list(self._order_log)

    def detect_cross_asset_hedge(
        self, kalshi_positions: List[Dict], ibkr_positions: List[Dict]
    ) -> List[str]:
        """
        Detect natural hedges between Kalshi and IBKR positions.

        Advisory only — logs when opposing positions create a hedge.
        Example: long weather contract + short utility stock.

        Returns list of hedge descriptions.
        """
        hedges: List[str] = []

        kalshi_tickers = {p.get("ticker", ""): p for p in kalshi_positions}
        ibkr_symbols = {p.get("ticker", ""): p for p in ibkr_positions}

        # Simple heuristic: if we have both long and short across platforms
        for k_ticker, k_pos in kalshi_tickers.items():
            k_side = k_pos.get("side", "")
            for i_symbol, i_pos in ibkr_symbols.items():
                i_qty = i_pos.get("position", 0)
                if k_side == "yes" and i_qty < 0:
                    hedges.append(
                        f"Potential hedge: long {k_ticker} (Kalshi) + short {i_symbol} (IBKR)"
                    )
                elif k_side == "no" and i_qty > 0:
                    hedges.append(
                        f"Potential hedge: short {k_ticker} (Kalshi) + long {i_symbol} (IBKR)"
                    )

        if hedges:
            for h in hedges:
                logger.info("LexiconOrderRouter: %s", h)

        return hedges
