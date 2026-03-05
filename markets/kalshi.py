"""
Kalshi Market Implementation

Wraps the existing AuthenticatedKalshiClient to implement the Market interface.
This allows the existing client to be used with the new plugin architecture.
"""

import logging
from typing import Any, Dict, List, Optional

from .base import Market

logger = logging.getLogger(__name__)


class KalshiMarket(Market):
    """
    Kalshi prediction market implementation.

    Wraps AuthenticatedKalshiClient to provide unified Market interface.
    Can be initialized with existing client or will create one on demand.

    Example:
        >>> from kalshi_trader import AuthenticatedKalshiClient
        >>> client = AuthenticatedKalshiClient(config)
        >>> await client.connect()
        >>> market = KalshiMarket({}, client)
        >>> markets = await market.get_open_markets(series="INXD")
    """

    def __init__(self, config: Dict[str, Any], client: Any = None):
        """
        Initialize Kalshi market.

        Args:
            config: Configuration dict (not used if client provided)
            client: Pre-initialized AuthenticatedKalshiClient
        """
        super().__init__(config, client)
        self._connected = client is not None

    @property
    def name(self) -> str:
        """Market identifier."""
        return "kalshi"

    @property
    def client(self):
        """Get the underlying Kalshi client."""
        if self._client is None:
            raise RuntimeError("KalshiMarket not connected. Call connect() first.")
        return self._client

    async def connect(self, kalshi_config=None) -> None:
        """
        Connect to Kalshi API if not already connected.

        Args:
            kalshi_config: KalshiConfig instance for creating new client
        """
        if self._connected:
            return

        if self._client is None and kalshi_config is not None:
            # Import here to avoid circular dependency
            from kalshi_trader import AuthenticatedKalshiClient

            self._client = AuthenticatedKalshiClient(kalshi_config)
            await self._client.connect()
            self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from Kalshi API."""
        if self._client and self._connected:
            await self._client.disconnect()
            self._connected = False

    async def get_open_markets(
        self,
        series: Optional[str] = None,
        status: str = "open",
        limit: int = 200,
    ) -> List[Dict]:
        """
        Fetch open Kalshi markets.

        For wildcard scans (series="*"), paginates to fetch up to 2000 markets.
        For specific series, fetches a single page (usually sufficient).

        Args:
            series: Market series (e.g., "INXD", "INXH", "*" for all)
            status: Market status filter
            limit: Maximum markets per page

        Returns:
            List of normalized market dicts
        """
        # Treat "*" as "all markets" — paginate to see the full market
        effective_series = None if series == "*" else series
        use_pagination = series == "*"

        markets = await self.client.get_markets(
            series_ticker=effective_series,
            status=status,
            limit=limit,
            paginate=use_pagination,
            max_pages=10,
        )

        logger.info(f"[kalshi] Fetched {len(markets)} markets (series={series}, paginated={use_pagination})")
        return markets

    async def get_market(self, ticker: str) -> Dict:
        """
        Get single Kalshi market by ticker.

        Args:
            ticker: Market ticker

        Returns:
            Normalized market dict
        """
        return await self.client.get_market(ticker)

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
        Place order on Kalshi.

        Args:
            ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price_cents: Limit price
            order_type: Order type (only "limit" supported)

        Returns:
            Order details dict
        """
        if order_type != "limit":
            logger.warning(f"Kalshi only supports limit orders, ignoring type={order_type}")

        return await self.client.create_limit_order(
            ticker=ticker,
            side=side,
            action=action,
            count=count,
            price_cents=price_cents,
        )

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel Kalshi order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancelled
        """
        return await self.client.cancel_order(order_id)

    async def get_positions(self) -> List[Dict]:
        """
        Get all Kalshi positions.

        Returns:
            List of position dicts
        """
        return await self.client.get_positions()

    async def get_balance(self) -> Dict[str, float]:
        """
        Get Kalshi account balance.

        Returns:
            Balance dict
        """
        return await self.client.get_balance()

    async def get_orderbook(self, ticker: str) -> Dict:
        """
        Get Kalshi orderbook.

        Args:
            ticker: Market ticker

        Returns:
            Orderbook dict
        """
        return await self.client.get_orderbook(ticker)

    async def cancel_all_orders(self, ticker: Optional[str] = None) -> int:
        """
        Cancel all Kalshi orders.

        Args:
            ticker: Optional market filter

        Returns:
            Number cancelled
        """
        return await self.client.cancel_all_orders(ticker)

    async def get_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get Kalshi orders.

        Args:
            ticker: Optional ticker filter
            status: Optional status filter

        Returns:
            List of order dicts
        """
        return await self.client.get_orders(ticker=ticker, status=status)
