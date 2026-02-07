"""
Market Base Classes

Abstract base class for all market data providers. Defines the interface that
all markets must implement for fetching data and placing orders.

Design Principles:
    - Markets are adapters over platform-specific APIs
    - Unified data format across all platforms
    - Async-first for performance
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MarketConfig:
    """
    Base configuration for market providers.

    Attributes:
        platform: Platform identifier (e.g., "kalshi")
        series: Market series to filter (e.g., "INXD")
        status: Market status filter (default: "open")
        limit: Maximum markets to fetch
    """

    platform: str
    series: Optional[str] = None
    status: str = "open"
    limit: int = 100


class Market(ABC):
    """
    Abstract base class for market data providers.

    Markets provide methods for fetching data and placing orders.
    Each platform (Kalshi, Polymarket, etc.) has its own implementation.

    Example Implementation:
        >>> class MyMarket(Market):
        ...     @property
        ...     def name(self) -> str:
        ...         return "my_platform"
        ...
        ...     async def get_open_markets(self, filters):
        ...         # Fetch from platform API
        ...         raw_data = await self._client.fetch_markets()
        ...         return [self._normalize(m) for m in raw_data]
    """

    def __init__(self, config: Dict[str, Any], client: Any = None):
        """
        Initialize market with configuration.

        Args:
            config: Market configuration dict
            client: Optional pre-initialized API client
        """
        self.config = config
        self._client = client

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique market identifier.

        Returns:
            Market name (e.g., "kalshi", "polymarket")
        """
        pass

    @abstractmethod
    async def get_open_markets(
        self,
        series: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
    ) -> List[Dict]:
        """
        Fetch open markets, optionally filtered.

        Returns normalized market data format for strategy consumption.

        Args:
            series: Filter by market series (platform-specific)
            status: Filter by status ("open", "closed", "settled")
            limit: Maximum markets to return

        Returns:
            List of normalized market dicts with keys:
                - ticker: Unique market identifier
                - title: Human-readable title
                - yes_bid: Best YES bid price (cents)
                - yes_ask: Best YES ask price (cents)
                - no_bid: Best NO bid price (cents)
                - no_ask: Best NO ask price (cents)
                - last_price: Last trade price (cents)
                - volume: Trading volume
                - volume_24h: 24-hour volume
                - open_interest: Open interest
                - close_time: Market close datetime
                - expiration_time: Settlement datetime
                - status: Market status
        """
        pass

    @abstractmethod
    async def get_market(self, ticker: str) -> Dict:
        """
        Get single market by ticker.

        Args:
            ticker: Market ticker

        Returns:
            Normalized market dict (same format as get_open_markets)

        Raises:
            MarketNotFoundError: If market doesn't exist
        """
        pass

    @abstractmethod
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
        Place an order on the market.

        Args:
            ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price_cents: Limit price in cents
            order_type: Order type (default: "limit")

        Returns:
            Order details dict with keys:
                - order_id: Unique order identifier
                - ticker: Market ticker
                - side: Order side
                - action: Order action
                - count: Contract count
                - price: Order price
                - status: Order status
                - created_time: Order creation time
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancelled successfully
        """
        pass

    @abstractmethod
    async def get_positions(self) -> List[Dict]:
        """
        Get all open positions.

        Returns:
            List of position dicts with keys:
                - ticker: Market ticker
                - position: Net position (positive=YES, negative=NO)
                - resting_orders_count: Number of open orders
                - realized_pnl: Realized profit/loss
        """
        pass

    @abstractmethod
    async def get_balance(self) -> Dict[str, float]:
        """
        Get account balance.

        Returns:
            Dict with keys:
                - balance: Total balance
                - available: Available for trading
                - portfolio_value: Value of open positions
        """
        pass

    async def get_orderbook(self, ticker: str) -> Dict:
        """
        Get orderbook for a market.

        Optional method - default returns empty orderbook.

        Args:
            ticker: Market ticker

        Returns:
            Dict with 'yes' and 'no' order books
        """
        return {"yes": [], "no": []}

    async def cancel_all_orders(self, ticker: Optional[str] = None) -> int:
        """
        Cancel all resting orders.

        Default implementation fetches orders and cancels individually.

        Args:
            ticker: Optional filter by market ticker

        Returns:
            Number of orders cancelled
        """
        # Subclasses can override for batch cancellation
        return 0

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
