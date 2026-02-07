"""
Trading Strategies Package

Plugin architecture for trading strategies. Each strategy implements the
base Strategy interface and can be dynamically loaded and configured.

Available Strategies:
    - MeanReversionStrategy: Buy near 50c, profit from reversion to mean
    - MomentumStrategy: Follow trends in price direction
    - CombinatorialArbitrageStrategy: Exploit pricing inconsistencies in related markets
    - CrossPlatformArbitrageStrategy: Compare Polymarket vs Kalshi prices

Example:
    >>> from strategies import load_strategy
    >>> strategy = load_strategy("mean_reversion", config)
    >>> opportunities = await strategy.scan_opportunities(markets)

Cross-Platform Example:
    >>> from strategies import CrossPlatformArbitrageStrategy
    >>> strategy = CrossPlatformArbitrageStrategy(config)
    >>> strategy.set_market_clients(kalshi_client, polymarket_client)
    >>> opportunities = await strategy.scan_opportunities(kalshi_markets)
"""

from .base import (
    Strategy,
    TradingOpportunity,
    ExitSignal,
    StrategyConfig,
)
from .mean_reversion import MeanReversionStrategy
from .momentum import MomentumStrategy
from .combinatorial_arbitrage import (
    CombinatorialArbitrageStrategy,
    MarketRelationshipGraph,
    ArbitrageScanner,
    MarketSet,
    MarketOutcome,
    ArbitrageOpportunity,
    ArbitrageLeg,
    RelationshipType,
    find_related_markets,
    check_arbitrage_opportunity,
    calculate_guaranteed_profit,
)
from .cross_platform_arbitrage import (
    CrossPlatformArbitrageStrategy,
    CrossPlatformSignal,
)

# Strategy registry - maps name to class
STRATEGY_REGISTRY = {
    "mean_reversion": MeanReversionStrategy,
    "momentum": MomentumStrategy,
    "combinatorial_arbitrage": CombinatorialArbitrageStrategy,
    "cross_platform_arbitrage": CrossPlatformArbitrageStrategy,
}


def load_strategy(name: str, config: dict) -> Strategy:
    """
    Load a strategy by name with configuration.

    Args:
        name: Strategy name (must be in STRATEGY_REGISTRY)
        config: Strategy-specific configuration dict

    Returns:
        Instantiated Strategy object

    Raises:
        ValueError: If strategy name not found
    """
    if name not in STRATEGY_REGISTRY:
        available = ", ".join(STRATEGY_REGISTRY.keys())
        raise ValueError(f"Unknown strategy '{name}'. Available: {available}")

    strategy_class = STRATEGY_REGISTRY[name]
    return strategy_class(config)


def register_strategy(name: str, strategy_class: type) -> None:
    """
    Register a new strategy class.

    Args:
        name: Strategy name for config/CLI
        strategy_class: Class that implements Strategy interface
    """
    if not issubclass(strategy_class, Strategy):
        raise TypeError(f"{strategy_class} must inherit from Strategy")

    STRATEGY_REGISTRY[name] = strategy_class


def list_strategies() -> list:
    """Return list of available strategy names."""
    return list(STRATEGY_REGISTRY.keys())


__all__ = [
    # Base classes
    "Strategy",
    "TradingOpportunity",
    "ExitSignal",
    "StrategyConfig",
    # Strategy implementations
    "MeanReversionStrategy",
    "MomentumStrategy",
    "CombinatorialArbitrageStrategy",
    "CrossPlatformArbitrageStrategy",
    # Combinatorial arbitrage components (for advanced usage)
    "MarketRelationshipGraph",
    "ArbitrageScanner",
    "MarketSet",
    "MarketOutcome",
    "ArbitrageOpportunity",
    "ArbitrageLeg",
    "RelationshipType",
    # Cross-platform arbitrage components
    "CrossPlatformSignal",
    # Utility functions
    "find_related_markets",
    "check_arbitrage_opportunity",
    "calculate_guaranteed_profit",
    "load_strategy",
    "register_strategy",
    "list_strategies",
    "STRATEGY_REGISTRY",
]
