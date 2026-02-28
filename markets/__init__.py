"""
Markets Package

Plugin architecture for market data providers. Each market implements the
base Market interface for fetching data and placing orders.

Available Markets:
    - KalshiMarket: Kalshi prediction market platform (full trading)
    - PolymarketMarket: Polymarket platform (read-only data source)
    - IBKRMarket: Interactive Brokers stock trading via TWS/Gateway

Example:
    >>> from markets import load_market
    >>> market = load_market("kalshi", config, client)
    >>> markets = await market.get_open_markets(series="INXD")

Cross-Platform Usage:
    >>> from markets import KalshiMarket, PolymarketMarket
    >>> kalshi = KalshiMarket({}, kalshi_client)
    >>> polymarket = PolymarketMarket({})
    >>> await polymarket.connect()
    >>> matches = polymarket.find_kalshi_matches(poly_markets, kalshi_markets)
"""

from .base import Market, MarketConfig
from .ibkr import IBKRMarket
from .ibkr_types import StockPosition
from .kalshi import KalshiMarket
from .polymarket import (
    PolymarketMarket,
    MarketMatcher,
    MarketMatchScore,
    MatchedMarketPair,
)

# Market registry - maps name to class
MARKET_REGISTRY = {
    "kalshi": KalshiMarket,
    "polymarket": PolymarketMarket,
    "ibkr": IBKRMarket,
}


def load_market(name: str, config: dict, client=None) -> Market:
    """
    Load a market by name with configuration.

    Args:
        name: Market name (must be in MARKET_REGISTRY)
        config: Market-specific configuration dict
        client: Optional pre-initialized client

    Returns:
        Instantiated Market object

    Raises:
        ValueError: If market name not found
    """
    if name not in MARKET_REGISTRY:
        available = ", ".join(MARKET_REGISTRY.keys())
        raise ValueError(f"Unknown market '{name}'. Available: {available}")

    market_class = MARKET_REGISTRY[name]
    return market_class(config, client)


def register_market(name: str, market_class: type) -> None:
    """
    Register a new market class.

    Args:
        name: Market name for config/CLI
        market_class: Class that implements Market interface
    """
    if not issubclass(market_class, Market):
        raise TypeError(f"{market_class} must inherit from Market")

    MARKET_REGISTRY[name] = market_class


def list_markets() -> list:
    """Return list of available market names."""
    return list(MARKET_REGISTRY.keys())


__all__ = [
    # Base classes
    "Market",
    "MarketConfig",
    # Market implementations
    "KalshiMarket",
    "PolymarketMarket",
    "IBKRMarket",
    # IBKR types
    "StockPosition",
    # Polymarket matching utilities
    "MarketMatcher",
    "MarketMatchScore",
    "MatchedMarketPair",
    # Registry functions
    "load_market",
    "register_market",
    "list_markets",
    "MARKET_REGISTRY",
]
