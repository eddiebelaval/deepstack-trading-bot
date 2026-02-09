"""
Strategy Manager - Multi-Strategy Orchestration

Orchestrates multiple trading strategies across multiple markets.
Handles strategy conflicts, risk allocation, and rate limiting.

Design Decisions:
- Strategy conflicts: Last strategy wins (skip conflicting trades)
- Risk allocation: Split max_position_size evenly across active strategies
- Rate limits: Add delay between strategy scans
- State management: Strategies store state in self, persisted via journal
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from strategies import Strategy, TradingOpportunity, ExitSignal, load_strategy
from markets import Market
from .market_cache import MarketCache, get_market_cache

logger = logging.getLogger(__name__)


@dataclass
class StrategyState:
    """State tracking for a single strategy."""

    strategy: Strategy
    markets: List[Dict[str, str]]  # [{"platform": "kalshi", "series": "INXD"}]
    enabled: bool = True
    positions: Set[str] = field(default_factory=set)  # Tickers this strategy owns
    last_scan_time: Optional[datetime] = None
    scan_count: int = 0
    trade_count: int = 0


class StrategyManager:
    """
    Orchestrates multiple strategies across multiple markets.

    Handles:
    - Loading and initializing strategies from config
    - Scanning all strategies for opportunities
    - Resolving conflicts (same ticker, opposite sides)
    - Risk allocation across strategies
    - Rate limiting between scans

    Example:
        >>> manager = StrategyManager(config, markets)
        >>> await manager.initialize()
        >>>
        >>> # In trading loop:
        >>> opportunities = await manager.scan_all_opportunities()
        >>> ranked = manager.rank_opportunities(opportunities)
        >>> for opp in ranked[:3]:
        ...     print(f"{opp.strategy_name}: {opp.ticker} {opp.side}")
    """

    # Rate limiting: minimum seconds between strategy scans
    MIN_SCAN_INTERVAL_SECONDS = 1.0

    def __init__(
        self,
        config: Dict[str, Any],
        markets: Dict[str, Market],
        max_position_size: float = 50.0,
        max_total_positions: int = 10,
        dry_run: bool = False,
    ):
        """
        Initialize strategy manager.

        Args:
            config: Full configuration dict with 'strategies' key
            markets: Dict of platform name -> Market instance
            max_position_size: Maximum position size per trade
            max_total_positions: Maximum concurrent positions across all strategies
            dry_run: If True, scan but don't execute trades
        """
        self.config = config
        self.dry_run = dry_run
        self.markets = markets
        self.max_position_size = max_position_size
        self.max_total_positions = max_total_positions

        self._strategies: Dict[str, StrategyState] = {}
        self._position_to_strategy: Dict[str, str] = {}  # ticker -> strategy name
        self._initialized = False

        # CryExc bridge (injected by main.py after initialization)
        self._cryexc_bridge = None

        # Market data cache to reduce API calls
        # TTL of 30 seconds balances freshness with API rate limits
        self._market_cache = get_market_cache(default_ttl=30.0, max_size=1000)

    @property
    def active_strategies(self) -> List[Strategy]:
        """Get list of enabled strategies."""
        return [
            state.strategy
            for state in self._strategies.values()
            if state.enabled
        ]

    @property
    def total_positions(self) -> int:
        """Get total open positions across all strategies."""
        return len(self._position_to_strategy)

    async def initialize(self) -> None:
        """
        Initialize all configured strategies.

        Loads strategy configurations from config and creates instances.
        """
        strategy_configs = self.config.get("strategies", [])

        if not strategy_configs:
            logger.warning("No strategies configured, using default mean_reversion")
            strategy_configs = [
                {
                    "name": "mean_reversion",
                    "enabled": True,
                    "markets": [{"platform": "kalshi", "series": "INXD"}],
                    "config": {},
                }
            ]

        for strategy_config in strategy_configs:
            name = strategy_config.get("name")
            enabled = strategy_config.get("enabled", True)
            markets = strategy_config.get("markets", [])
            config = strategy_config.get("config", {})

            if not name:
                logger.warning("Strategy config missing 'name', skipping")
                continue

            try:
                # Load strategy from registry
                strategy = load_strategy(name, config)

                # Inject market clients into strategies that need them
                self._inject_market_clients(strategy, markets)

                # Validate config
                valid, error = strategy.validate_config()
                if not valid:
                    logger.error(f"Strategy '{name}' config invalid: {error}")
                    continue

                # Create state tracker
                self._strategies[name] = StrategyState(
                    strategy=strategy,
                    markets=markets,
                    enabled=enabled,
                )

                logger.info(
                    f"Loaded strategy '{name}' | "
                    f"Enabled: {enabled} | "
                    f"Markets: {len(markets)}"
                )

            except Exception as e:
                logger.error(f"Failed to load strategy '{name}': {e}")

        self._initialized = True
        logger.info(f"StrategyManager initialized with {len(self._strategies)} strategies")

    def _inject_market_clients(self, strategy: Strategy, markets_config: List[Dict]) -> None:
        """
        Inject market clients into strategies that need them.

        Strategies like cross_platform_arbitrage need access to multiple
        market clients (e.g., Polymarket for data, Kalshi for execution).

        Args:
            strategy: The strategy instance to inject clients into
            markets_config: List of market configs for this strategy
        """
        # Check which platforms this strategy needs
        needed_platforms = {m.get("platform", "kalshi") for m in markets_config}

        # Inject Polymarket client if needed and available
        if "polymarket" in needed_platforms and "polymarket" in self.markets:
            if hasattr(strategy, "_polymarket_client"):
                strategy._polymarket_client = self.markets["polymarket"]
                logger.debug(f"Injected Polymarket client into {strategy.name}")

        # Inject Kalshi client if needed
        if "kalshi" in needed_platforms and "kalshi" in self.markets:
            if hasattr(strategy, "_kalshi_client"):
                strategy._kalshi_client = self.markets["kalshi"]
                logger.debug(f"Injected Kalshi client into {strategy.name}")

        # Inject matcher if strategy needs it
        if hasattr(strategy, "_matcher") and strategy._matcher is None:
            try:
                from markets.polymarket import MarketMatcher
                strategy._matcher = MarketMatcher()
                logger.debug(f"Injected MarketMatcher into {strategy.name}")
            except ImportError:
                pass

        # Inject CryExc bridge if available and strategy supports it
        if self._cryexc_bridge and hasattr(strategy, "_cryexc_bridge"):
            strategy._cryexc_bridge = self._cryexc_bridge
            logger.debug(f"Injected CryExc bridge into {strategy.name}")

    async def scan_all_opportunities(
        self,
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan all enabled strategies across all markets.

        Args:
            existing_positions: Dict of ticker -> position data to skip

        Returns:
            List of TradingOpportunity from all strategies, sorted by score
        """
        if not self._initialized:
            await self.initialize()

        existing_positions = existing_positions or {}
        all_opportunities: List[TradingOpportunity] = []

        for name, state in self._strategies.items():
            if not state.enabled:
                continue

            try:
                # Rate limiting between strategies
                if state.last_scan_time:
                    elapsed = (datetime.now() - state.last_scan_time).total_seconds()
                    if elapsed < self.MIN_SCAN_INTERVAL_SECONDS:
                        await asyncio.sleep(self.MIN_SCAN_INTERVAL_SECONDS - elapsed)

                # Scan each market for this strategy
                for market_config in state.markets:
                    platform = market_config.get("platform", "kalshi")
                    series = market_config.get("series")

                    if platform not in self.markets:
                        logger.warning(f"Market '{platform}' not available")
                        continue

                    market = self.markets[platform]

                    # Fetch market data (with caching)
                    cache_key = f"markets:{platform}:{series or 'all'}"
                    markets_data = await self._market_cache.get_or_fetch(
                        cache_key,
                        lambda: market.get_open_markets(series=series),
                        ttl=30.0,  # 30 second TTL for market lists
                    )

                    # Find opportunities
                    opportunities = await state.strategy.scan_opportunities(
                        markets=markets_data,
                        existing_positions=existing_positions,
                    )

                    all_opportunities.extend(opportunities)

                state.last_scan_time = datetime.now()
                state.scan_count += 1

            except Exception as e:
                logger.error(f"Error scanning strategy '{name}': {e}")

        # Sort by score (best first)
        all_opportunities.sort(key=lambda x: x.score, reverse=True)

        logger.debug(
            f"Found {len(all_opportunities)} total opportunities "
            f"from {len(self.active_strategies)} strategies"
        )

        return all_opportunities

    def rank_opportunities(
        self,
        opportunities: List[TradingOpportunity],
        max_results: int = 10,
    ) -> List[TradingOpportunity]:
        """
        Rank and filter opportunities.

        Applies:
        - Conflict resolution (same ticker, opposite sides)
        - Portfolio capacity checks
        - Diversification rules

        Args:
            opportunities: List of opportunities to rank
            max_results: Maximum opportunities to return

        Returns:
            Filtered and ranked opportunities
        """
        if not opportunities:
            return []

        # Remove duplicates (same ticker from different strategies)
        seen_tickers: Dict[str, TradingOpportunity] = {}
        conflicts: List[Tuple[str, str, str]] = []  # (ticker, side1, side2)

        for opp in opportunities:
            ticker = opp.ticker

            if ticker in seen_tickers:
                existing = seen_tickers[ticker]

                # Check for conflict (opposite sides)
                if existing.side != opp.side:
                    conflicts.append((ticker, existing.side, opp.side))
                    logger.debug(
                        f"Conflict on {ticker}: "
                        f"{existing.strategy_name} wants {existing.side}, "
                        f"{opp.strategy_name} wants {opp.side}"
                    )
                    # Last strategy wins - keep the new one if higher score
                    if opp.score > existing.score:
                        seen_tickers[ticker] = opp
                else:
                    # Same side - keep higher score
                    if opp.score > existing.score:
                        seen_tickers[ticker] = opp
            else:
                seen_tickers[ticker] = opp

        # Apply portfolio capacity
        remaining_capacity = self.max_total_positions - self.total_positions
        ranked = list(seen_tickers.values())
        ranked.sort(key=lambda x: x.score, reverse=True)

        # Limit results
        return ranked[:min(max_results, remaining_capacity)]

    async def check_all_exits(
        self,
        positions: Dict[str, Dict[str, Any]],
        market: Market,
    ) -> List[Tuple[str, ExitSignal]]:
        """
        Check exit conditions for all positions.

        Args:
            positions: Dict of ticker -> position data
            market: Market instance for fetching current prices

        Returns:
            List of (ticker, ExitSignal) for positions that should exit
        """
        exits: List[Tuple[str, ExitSignal]] = []

        for ticker, position in positions.items():
            try:
                # Get strategy that owns this position
                strategy_name = position.get("strategy", "mean_reversion")
                state = self._strategies.get(strategy_name)

                if not state:
                    logger.warning(f"No strategy '{strategy_name}' for position {ticker}")
                    continue

                # Get current market data
                market_data = await market.get_market(ticker)

                # Determine current price for position side
                side = position.get("side", "yes")
                if side == "yes":
                    current_price = market_data.get("yes_bid", 50)
                else:
                    current_price = market_data.get("no_bid", 50)

                # Check exit conditions
                exit_signal = await state.strategy.check_exit(
                    position=position,
                    current_price=current_price,
                    market_data=market_data,
                )

                if exit_signal.should_exit:
                    exits.append((ticker, exit_signal))

            except Exception as e:
                logger.error(f"Error checking exit for {ticker}: {e}")

        return exits

    def get_position_size_for_strategy(self, strategy_name: str) -> float:
        """
        Calculate position size allocation for a strategy.

        Risk allocation: Split max_position_size evenly across active strategies.

        Args:
            strategy_name: Strategy to calculate size for

        Returns:
            Maximum position size in dollars for this strategy
        """
        active_count = len(self.active_strategies)
        if active_count == 0:
            return self.max_position_size

        # Even split across strategies
        return self.max_position_size / active_count

    def record_position_open(self, ticker: str, strategy_name: str) -> None:
        """
        Record that a position was opened.

        Args:
            ticker: Market ticker
            strategy_name: Strategy that opened it
        """
        self._position_to_strategy[ticker] = strategy_name

        if strategy_name in self._strategies:
            self._strategies[strategy_name].positions.add(ticker)
            self._strategies[strategy_name].trade_count += 1

    def record_position_close(self, ticker: str) -> None:
        """
        Record that a position was closed.

        Args:
            ticker: Market ticker
        """
        strategy_name = self._position_to_strategy.pop(ticker, None)

        if strategy_name and strategy_name in self._strategies:
            self._strategies[strategy_name].positions.discard(ticker)

    def enable_strategy(self, name: str) -> bool:
        """Enable a strategy by name."""
        if name in self._strategies:
            self._strategies[name].enabled = True
            logger.info(f"Strategy '{name}' enabled")
            return True
        return False

    def disable_strategy(self, name: str) -> bool:
        """Disable a strategy by name."""
        if name in self._strategies:
            self._strategies[name].enabled = False
            logger.info(f"Strategy '{name}' disabled")
            return True
        return False

    def get_strategy_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get statistics for all strategies.

        Returns:
            Dict of strategy name -> stats dict
        """
        stats = {}
        for name, state in self._strategies.items():
            stats[name] = {
                "enabled": state.enabled,
                "positions": len(state.positions),
                "scan_count": state.scan_count,
                "trade_count": state.trade_count,
                "last_scan": state.last_scan_time.isoformat() if state.last_scan_time else None,
                "edge": state.strategy.calculate_edge(),
            }
        return stats

    def __repr__(self) -> str:
        active = len(self.active_strategies)
        total = len(self._strategies)
        return f"StrategyManager(active={active}/{total}, positions={self.total_positions})"
