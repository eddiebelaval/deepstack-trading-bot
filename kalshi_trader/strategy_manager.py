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
import inspect
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
    accepts_governance: bool = False  # Cached: does scan_opportunities accept governance_engine?


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
        max_per_series: int = 2,
        dry_run: bool = False,
    ):
        """
        Initialize strategy manager.

        Args:
            config: Full configuration dict with 'strategies' key
            markets: Dict of platform name -> Market instance
            max_position_size: Maximum position size per trade
            max_total_positions: Maximum concurrent positions across all strategies
            max_per_series: Maximum opportunities per series_ticker (correlation cap)
            dry_run: If True, scan but don't execute trades
        """
        self.config = config
        self.dry_run = dry_run
        self.markets = markets
        self.max_position_size = max_position_size
        self.max_total_positions = max_total_positions
        self.max_per_series = max_per_series

        self._strategies: Dict[str, StrategyState] = {}
        self._position_to_strategy: Dict[str, str] = {}  # ticker -> strategy name
        self._initialized = False

        # CryExc bridge (injected by main.py after initialization)
        self._cryexc_bridge = None

        # Per-strategy error counters (reset on restart).
        # Used by heartbeat error rate monitor to auto-disable broken strategies.
        self._error_counts: Dict[str, int] = {}
        self._trade_counts: Dict[str, int] = {}

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

    def _increment_error_count(self, strategy_name: str) -> None:
        """Increment per-strategy error counter."""
        self._error_counts[strategy_name] = self._error_counts.get(strategy_name, 0) + 1

    def _increment_trade_count(self, strategy_name: str) -> None:
        """Increment per-strategy trade counter."""
        self._trade_counts[strategy_name] = self._trade_counts.get(strategy_name, 0) + 1

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

                # Create state tracker (cache governance_engine support check)
                accepts_gov = "governance_engine" in inspect.signature(
                    strategy.scan_opportunities
                ).parameters
                self._strategies[name] = StrategyState(
                    strategy=strategy,
                    markets=markets,
                    enabled=enabled,
                    accepts_governance=accepts_gov,
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
        governance_engine: Optional[Any] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan all enabled strategies across all markets.

        Args:
            existing_positions: Dict of ticker -> position data to skip
            governance_engine: GovernanceEngine for regime-aware strategies

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
                    # Some market configs are dependencies/data-sources only (e.g. polymarket for
                    # cross_platform_arbitrage). Keep them for client injection, but don't scan them.
                    if market_config.get("scan", True) is False:
                        continue

                    platform = market_config.get("platform", "kalshi")
                    series = market_config.get("series")

                    if platform not in self.markets:
                        logger.warning(f"Market '{platform}' not available")
                        continue

                    try:
                        market = self.markets[platform]

                        # Fetch market data (with caching)
                        # IBKR uses special series values for different asset classes
                        cache_key = f"markets:{platform}:{series or 'all'}"
                        ibkr_timeout = 15  # seconds — prevent IBKR hangs from blocking cycle
                        if platform == "ibkr" and series == "futures":
                            markets_data = await asyncio.wait_for(
                                self._market_cache.get_or_fetch(
                                    cache_key,
                                    lambda: market.get_futures_markets(),
                                    ttl=30.0,
                                ),
                                timeout=ibkr_timeout,
                            )
                        elif platform == "ibkr" and series == "options":
                            # Fetch option chains for each underlying in the watchlist
                            async def _fetch_all_options():
                                stocks = await market.get_open_markets()
                                all_options = []
                                for stock in stocks[:10]:  # Cap at 10 underlyings
                                    sym = stock.get("ticker", "")
                                    if not sym:
                                        continue
                                    try:
                                        chain = await market.get_options_chain(sym)
                                        all_options.extend(chain)
                                    except Exception as e:
                                        logger.debug(f"Options chain fetch failed for {sym}: {e}")
                                return all_options

                            markets_data = await asyncio.wait_for(
                                self._market_cache.get_or_fetch(
                                    cache_key,
                                    _fetch_all_options,
                                    ttl=60.0,  # Longer TTL — option chains are expensive
                                ),
                                timeout=60,  # Longer timeout — fetching multiple chains
                            )
                        elif platform == "ibkr" and series == "*":
                            markets_data = await asyncio.wait_for(
                                self._market_cache.get_or_fetch(
                                    cache_key,
                                    lambda: market.get_open_markets(),
                                    ttl=30.0,
                                ),
                                timeout=ibkr_timeout,
                            )
                        else:
                            markets_data = await self._market_cache.get_or_fetch(
                                cache_key,
                                lambda: market.get_open_markets(series=series),
                                ttl=30.0,
                            )

                        # Find opportunities — pass governance_engine to
                        # strategies that accept it (e.g. stock_momentum)
                        kwargs: Dict[str, Any] = {
                            "markets": markets_data,
                            "existing_positions": existing_positions,
                        }
                        if state.accepts_governance and governance_engine:
                            kwargs["governance_engine"] = governance_engine

                        opportunities = await state.strategy.scan_opportunities(**kwargs)

                        all_opportunities.extend(opportunities)
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Strategy '{name}' series '{series}' fetch timed out — skipping"
                        )
                        self._increment_error_count(name)
                    except Exception as e:
                        logger.error(
                            f"Error scanning strategy '{name}' series '{series}': {e}"
                        )
                        self._increment_error_count(name)

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
        - Correlation guard (max opportunities per series_ticker)
        - Portfolio capacity checks

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

        # Correlation guard: cap opportunities per series_ticker
        ranked = list(seen_tickers.values())
        ranked.sort(key=lambda x: x.score, reverse=True)

        series_counts: Dict[str, int] = {}
        correlated_filtered: List[TradingOpportunity] = []
        for opp in ranked:
            series = opp.ticker.split("-")[0]
            count = series_counts.get(series, 0)
            if count >= self.max_per_series:
                logger.info(
                    f"Correlation guard: dropping {opp.ticker} "
                    f"(series {series} already has {count} opportunities, "
                    f"max_per_series={self.max_per_series})"
                )
                continue
            series_counts[series] = count + 1
            correlated_filtered.append(opp)

        # Apply portfolio capacity
        remaining_capacity = self.max_total_positions - self.total_positions

        # Limit results
        return correlated_filtered[:min(max_results, remaining_capacity)]

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
