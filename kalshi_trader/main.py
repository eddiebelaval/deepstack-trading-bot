"""
Kalshi Trading Bot - Main Entry Point

Production trading loop for Kalshi prediction markets.
Orchestrates all components: API client, risk management, strategies, and journaling.

Supports two modes:
1. Legacy mode: Single mean-reversion strategy (backward compatible)
2. Multi-strategy mode: Multiple strategies via StrategyManager

Usage:
    # As a module
    from kalshi_trader import KalshiTradingBot
    bot = KalshiTradingBot()
    await bot.start()

    # From command line
    python run_bot.py

    # Multi-strategy mode
    python run_bot.py --strategies=mean_reversion,momentum --profile=aggressive
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .command_processor import CommandProcessor
from .config import KalshiConfig, load_config, get_strategy_configs, load_yaml_config, CryExcConfig
from .dashboard_sync import DashboardSync
from .kalshi_client import AuthenticatedKalshiClient
from .deepstack_integration import DeepStackIntegration
from .journal import TradeJournal
from .performance_tracker import PerformanceTracker
from .exceptions import (
    KalshiTradingError,
    DailyLossLimitHit,
    RiskLimitExceeded,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class KalshiTradingBot:
    """
    Production trading bot for Kalshi prediction markets.

    Implements a complete trading loop with:
    - Multi-strategy support via StrategyManager (or legacy single strategy)
    - Kelly Criterion position sizing
    - Emotional firewall protection
    - SQLite trade journaling
    - Graceful shutdown handling

    Example:
        >>> config = KalshiConfig()
        >>> bot = KalshiTradingBot(config)
        >>> await bot.start()  # Runs until stopped

        # Or with signal handling
        >>> asyncio.run(bot.start())  # Ctrl+C to stop

        # Multi-strategy mode
        >>> bot = KalshiTradingBot(config, use_strategy_manager=True)
        >>> await bot.start()
    """

    def __init__(
        self,
        config: Optional[KalshiConfig] = None,
        use_strategy_manager: bool = False,
        strategy_configs: Optional[List[Dict]] = None,
        dry_run: bool = False,
    ):
        """
        Initialize trading bot.

        Args:
            config: KalshiConfig (loads from env if not provided)
            use_strategy_manager: Use multi-strategy mode (default: False for backward compat)
            strategy_configs: Custom strategy configs (overrides YAML)
            dry_run: If True, scan for opportunities but don't execute trades
        """
        self.config = config or load_config()
        self.use_strategy_manager = use_strategy_manager
        self.strategy_configs = strategy_configs
        self.dry_run = dry_run

        self.client: Optional[AuthenticatedKalshiClient] = None
        self.risk: Optional[DeepStackIntegration] = None
        self.journal: Optional[TradeJournal] = None
        self.performance_tracker: Optional[PerformanceTracker] = None
        self.dashboard: Optional[DashboardSync] = None
        self.command_processor: Optional[CommandProcessor] = None

        # Strategy handling
        self.strategy = None  # Legacy single strategy
        self.strategy_manager = None  # Multi-strategy manager
        self.market = None  # Market adapter for StrategyManager

        # CryExc real-time exchange data bridge (optional, enabled via config)
        self._cryexc_bridge = None

        self._running = False
        self._paused = False
        self._shutdown_event = asyncio.Event()

        # Track open positions
        self.open_positions: Dict[str, Dict[str, Any]] = {}

        logger.info(
            f"KalshiTradingBot initialized | "
            f"Series: {self.config.market_series} | "
            f"Max position: ${self.config.max_position_size} | "
            f"Daily loss limit: ${self.config.daily_loss_limit} | "
            f"Multi-strategy: {use_strategy_manager} | "
            f"Dry-run: {dry_run}"
        )

    async def start(self) -> None:
        """
        Start the trading bot.

        Initializes all components, connects to API, and runs the trading loop.
        Handles graceful shutdown on SIGINT/SIGTERM.
        """
        logger.info("Starting Kalshi Trading Bot...")

        # Setup signal handlers
        self._setup_signal_handlers()

        try:
            # Initialize components
            await self._initialize()

            # Start both loops concurrently
            self._running = True
            command_task = asyncio.create_task(self._command_loop())
            trading_task = asyncio.create_task(self._trading_loop())

            # Wait for trading loop to finish (command loop stops when _running=False)
            await trading_task
            command_task.cancel()
            try:
                await command_task
            except asyncio.CancelledError:
                pass

        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            raise
        finally:
            await self._shutdown()

    async def stop(self) -> None:
        """Signal the bot to stop gracefully."""
        logger.info("Stop requested...")
        self._running = False
        self._shutdown_event.set()

    async def _initialize(self) -> None:
        """Initialize all bot components."""
        logger.info("Initializing components...")

        # 1. Initialize Kalshi client
        self.client = AuthenticatedKalshiClient(self.config)
        await self.client.connect()

        # 2. Get initial balance
        balance = await self.client.get_balance()
        account_balance = balance["available"]
        logger.info(f"Account balance: ${account_balance:.2f}")

        # 3. Initialize risk management
        self.risk = DeepStackIntegration(self.config, account_balance)

        # 4. Initialize strategy/strategies
        if self.use_strategy_manager:
            await self._initialize_strategy_manager()
        else:
            await self._initialize_legacy_strategy()

        # 4b. Initialize CryExc real-time exchange data (optional)
        await self._initialize_cryexc()

        # 5. Initialize journal
        self.journal = TradeJournal(self.config.journal_db_path)

        # 5b. Initialize learning loop (same DB as journal)
        self.performance_tracker = PerformanceTracker(
            db_path=self.config.journal_db_path,
            prior_strength=getattr(self.config, 'learning_prior_strength', 20),
            decay_half_life_days=getattr(self.config, 'learning_decay_half_life', 30.0),
            auto_disable=getattr(self.config, 'learning_auto_disable', False),
        )
        self._register_strategy_priors()

        # 6. Initialize dashboard sync (Supabase, fire-and-forget)
        self.dashboard = DashboardSync()
        await self.dashboard.connect()

        # 6b. Restore strategy enabled states from Supabase (persists user toggles across restarts)
        if self.strategy_manager:
            overrides = await self.dashboard.get_strategy_overrides()
            restored = 0
            for name, enabled in overrides.items():
                if name in self.strategy_manager._strategies:
                    state = self.strategy_manager._strategies[name]
                    if state.enabled != enabled:
                        state.enabled = enabled
                        restored += 1
                        logger.info(f"Restored strategy '{name}' enabled={enabled} from dashboard")
            if restored:
                logger.info(f"Restored {restored} strategy toggle(s) from Supabase")

        # 7. Initialize command processor (Supabase polling)
        self.command_processor = CommandProcessor(self)
        await self.command_processor.connect()

        # 8. Load existing positions
        await self._sync_positions()

        # 9. Update bot config to running
        await self.command_processor.update_mode("running")
        await self.dashboard.push_log("Bot initialized — connected to Kalshi API", strategy="system")

        logger.info("All components initialized successfully")

    async def _initialize_legacy_strategy(self) -> None:
        """Initialize single mean-reversion strategy (backward compatible)."""
        # Import here to avoid issues if strategies package not available
        try:
            from strategies import MeanReversionStrategy
            strategy_config = {
                "price_floor_cents": self.config.price_floor_cents,
                "price_ceiling_cents": self.config.price_ceiling_cents,
                "take_profit_cents": self.config.take_profit_cents,
                "stop_loss_cents": self.config.stop_loss_cents,
                "min_volume": self.config.min_volume,
            }
            self.strategy = MeanReversionStrategy(strategy_config)
            logger.info("Using new MeanReversionStrategy from strategies package")
        except ImportError:
            # Fallback to old strategy module
            from .strategy import MeanReversionStrategy as LegacyStrategy
            self.strategy = LegacyStrategy(self.config)
            logger.info("Using legacy MeanReversionStrategy")

    async def _initialize_strategy_manager(self) -> None:
        """Initialize multi-strategy manager with all required market clients."""
        from .strategy_manager import StrategyManager
        from markets import KalshiMarket, PolymarketMarket

        # Get strategy configs
        if self.strategy_configs:
            configs = self.strategy_configs
        else:
            configs = get_strategy_configs()

        # Determine which platforms are needed by scanning strategy configs
        required_platforms = set()
        for strategy_config in configs:
            if strategy_config.get("enabled", True):
                for market_config in strategy_config.get("markets", []):
                    platform = market_config.get("platform", "kalshi")
                    required_platforms.add(platform)

        logger.info(f"Required platforms: {required_platforms}")

        # Create market adapters for each required platform
        markets_dict = {}

        # Always create Kalshi (execution target)
        self.market = KalshiMarket({}, self.client)
        markets_dict["kalshi"] = self.market

        # Create Polymarket if needed (read-only data source)
        if "polymarket" in required_platforms:
            try:
                polymarket = PolymarketMarket({})
                await polymarket.connect()
                markets_dict["polymarket"] = polymarket
                logger.info("Polymarket client initialized (read-only)")
            except Exception as e:
                logger.warning(f"Failed to initialize Polymarket: {e}")

        # Create manager with config
        manager_config = {"strategies": configs}
        self.strategy_manager = StrategyManager(
            config=manager_config,
            markets=markets_dict,
            max_position_size=self.config.max_position_size,
            dry_run=getattr(self, 'dry_run', False),
        )

        await self.strategy_manager.initialize()
        logger.info(f"StrategyManager initialized: {self.strategy_manager}")

    async def _initialize_cryexc(self) -> None:
        """Initialize CryExc real-time exchange data bridge (optional)."""
        # Load cryexc config from YAML
        yaml_config = load_yaml_config()
        if not yaml_config or not yaml_config.cryexc.enabled:
            logger.info("CryExc integration disabled (cryexc.enabled=false)")
            return

        try:
            from .cryexc_bridge import CryExcBridge

            cryexc_config = yaml_config.cryexc.model_dump()
            self._cryexc_bridge = CryExcBridge(cryexc_config)
            connected = await self._cryexc_bridge.connect()

            if connected:
                # Inject bridge into strategy manager for strategy access
                if self.strategy_manager:
                    self.strategy_manager._cryexc_bridge = self._cryexc_bridge

                logger.info("CryExc bridge connected — real-time exchange data active")
            else:
                logger.warning("CryExc bridge failed to connect — using fallback data sources")
                self._cryexc_bridge = None

        except ImportError as e:
            logger.warning(f"CryExc bridge import failed: {e}")
            self._cryexc_bridge = None
        except Exception as e:
            logger.warning(f"CryExc initialization failed: {e}")
            self._cryexc_bridge = None

    def _register_strategy_priors(self) -> None:
        """Register priors and attach tracker to all active strategies."""
        if not self.performance_tracker:
            return

        # Multi-strategy mode
        if self.strategy_manager:
            for name, state in self.strategy_manager._strategies.items():
                strategy = state.strategy
                prior_stats = strategy._get_prior_stats()
                self.performance_tracker.register_prior(name, prior_stats)
                strategy._performance_tracker = self.performance_tracker
                logger.info(
                    f"Learning loop attached: {name} | "
                    f"prior WR={prior_stats['win_rate']:.0%}"
                )
            return

        # Legacy single strategy (new strategies package)
        if self.strategy and hasattr(self.strategy, '_get_prior_stats'):
            prior_stats = self.strategy._get_prior_stats()
            self.performance_tracker.register_prior(self.strategy.name, prior_stats)
            self.strategy._performance_tracker = self.performance_tracker
            logger.info(f"Learning loop attached: {self.strategy.name}")

    async def _shutdown(self) -> None:
        """Clean shutdown of all components."""
        logger.info("Shutting down...")

        try:
            # Push shutdown state to Supabase
            if self.command_processor:
                await self.command_processor.update_mode("stopped")
            if self.dashboard:
                await self.dashboard.push_log("Bot shutting down", level="WARNING", strategy="system")

            # Disconnect CryExc bridge
            if self._cryexc_bridge:
                await self._cryexc_bridge.disconnect()

            # Cancel all open orders
            if self.client:
                cancelled = await self.client.cancel_all_orders()
                if cancelled > 0:
                    logger.info(f"Cancelled {cancelled} open orders")

            # Generate daily summary
            if self.journal:
                summary = self.journal.generate_daily_summary()
                logger.info(f"\n{summary}")
                self.journal.save_daily_summary()

            # Close performance tracker
            if self.performance_tracker:
                self.performance_tracker.close()

            # Disconnect command processor
            if self.command_processor:
                await self.command_processor.disconnect()

            # Disconnect dashboard sync
            if self.dashboard:
                await self.dashboard.disconnect()

            # Disconnect client
            if self.client:
                await self.client.disconnect()

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        logger.info("Shutdown complete")

    def _setup_signal_handlers(self) -> None:
        """Setup handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()

        def handle_signal():
            logger.info("Received shutdown signal")
            asyncio.create_task(self.stop())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                signal.signal(sig, lambda s, f: handle_signal())

    async def _command_loop(self) -> None:
        """Fast command polling loop (3s) — runs alongside trading loop."""
        logger.info("Command loop started (3s polling)")
        heartbeat_counter = 0

        while self._running:
            try:
                if self.command_processor:
                    await self.command_processor.poll_and_execute()

                    # Send heartbeat every ~30s (every 10th iteration)
                    heartbeat_counter += 1
                    if heartbeat_counter >= 10:
                        await self.command_processor.send_heartbeat()
                        heartbeat_counter = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Command loop error: {e}")

            await asyncio.sleep(3)

        logger.info("Command loop stopped")

    async def _trading_loop(self) -> None:
        """Main trading loop."""
        logger.info(
            f"Trading loop started | Poll interval: {self.config.poll_interval_seconds}s"
        )

        while self._running:
            try:
                await self._trading_cycle()

            except DailyLossLimitHit as e:
                logger.warning(f"Daily loss limit hit: {e}")
                logger.info("Pausing until next trading day...")
                # Wait until midnight or shutdown
                await self._wait_for_next_day()

            except RiskLimitExceeded as e:
                logger.warning(f"Risk limit exceeded: {e}")
                # Continue loop, will be blocked until cooldown expires

            except KalshiTradingError as e:
                logger.error(f"Trading error: {e}")
                # Brief pause before retrying
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Unexpected error in trading cycle: {e}", exc_info=True)
                await asyncio.sleep(10)

            # Wait for next cycle or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.config.poll_interval_seconds,
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Normal - continue to next cycle

    async def _trading_cycle(self) -> None:
        """Single trading cycle: update state, manage positions, find opportunities."""
        logger.debug("Starting trading cycle...")

        # 1. Update state (always, even when paused)
        await self._update_state()

        # Skip market scanning if paused
        if self._paused:
            logger.debug("Bot paused — skipping market scan")
            return

        # 2. Check risk limits
        risk_check = self.risk.check_trade_allowed("", None)
        if not risk_check["allowed"]:
            logger.info(f"Trading blocked: {risk_check['reasons']}")
            return

        # 3. Manage existing positions
        await self._manage_positions()

        # 4. Scan for opportunities
        if self.use_strategy_manager:
            await self._scan_and_trade_multi()
        else:
            await self._scan_and_trade_legacy()

        logger.debug("Trading cycle complete")

    async def _update_state(self) -> None:
        """Update account balance and position state, then push to dashboard."""
        # Get current balance
        balance = await self.client.get_balance()
        self.risk.update_balance(balance["available"])

        # Sync positions with exchange
        await self._sync_positions()

        # Push state to Supabase for dashboard (fire-and-forget)
        if self.dashboard:
            balance_cents = int(balance["balance"] * 100)
            available_cents = int(balance["available"] * 100)
            daily_stats = self.risk.get_daily_stats()
            daily_pnl_cents = int(daily_stats["daily_pnl"] * 100)

            # Build strategy info (with learning stats when tracker is active)
            strategies = []
            if self.strategy_manager:
                for name, state in self.strategy_manager._strategies.items():
                    strategy_info = {
                        "name": name,
                        "enabled": state.enabled,
                        "active_positions": len(state.positions),
                        "opportunities_found": state.scan_count,
                        "last_scan": state.last_scan_time.isoformat() if state.last_scan_time else None,
                        "status": "active" if state.enabled else "inactive",
                    }

                    # Add learning stats if tracker is active
                    if self.performance_tracker:
                        blended = self.performance_tracker.get_blended_stats(name)
                        prior = self.performance_tracker.get_prior(name)
                        if prior:
                            n = self.performance_tracker._get_effective_trade_count(name)
                            k = prior.prior_strength
                            strategy_info["blended_win_rate"] = round(blended["win_rate"], 4)
                            strategy_info["learning_confidence"] = round(n / (n + k), 4) if (n + k) > 0 else 0
                            strategy_info["effective_trades"] = round(n, 1)

                    strategies.append(strategy_info)

            await self.dashboard.push_state(
                balance_cents=balance_cents,
                available_balance_cents=available_cents,
                daily_pnl_cents=daily_pnl_cents,
                total_positions=len(self.open_positions),
                strategies=strategies,
                risk_config={
                    "daily_loss_limit": self.config.daily_loss_limit,
                    "max_position_size": self.config.max_position_size,
                    "kelly_fraction": self.config.kelly_fraction,
                },
            )

    async def _sync_positions(self) -> None:
        """Sync local position tracking with exchange."""
        positions = await self.client.get_positions()

        # Update local tracking
        exchange_tickers = set()
        for pos in positions:
            ticker = pos.get("market_ticker") or pos.get("ticker")
            if ticker and pos.get("position", 0) != 0:
                exchange_tickers.add(ticker)

                # If not in local tracking, add it
                if ticker not in self.open_positions:
                    self.open_positions[ticker] = {
                        "contracts": abs(pos["position"]),
                        "side": "yes" if pos["position"] > 0 else "no",
                        "synced_from_exchange": True,
                    }

        # Remove closed positions
        closed = [t for t in self.open_positions if t not in exchange_tickers]
        for ticker in closed:
            del self.open_positions[ticker]
            # Notify strategy manager if using it
            if self.strategy_manager:
                self.strategy_manager.record_position_close(ticker)

    async def _manage_positions(self) -> None:
        """Check exit conditions for open positions."""
        if not self.open_positions:
            return

        for ticker, position in list(self.open_positions.items()):
            try:
                # Get current market price
                market = await self.client.get_market(ticker)

                if market.get("status") not in ("open", "active"):
                    logger.info(f"Market {ticker} no longer open, removing from tracking")
                    del self.open_positions[ticker]
                    continue

                # Determine current price for our side
                if position["side"] == "yes":
                    current_price = market.get("yes_bid", 50)
                else:
                    current_price = market.get("no_bid", 50)

                # Check exit conditions
                if self.use_strategy_manager:
                    exit_signal = await self._check_exit_multi(position, current_price, market)
                else:
                    exit_signal = self._check_exit_legacy(position, current_price)

                if exit_signal and exit_signal.should_exit:
                    logger.info(f"Exit signal for {ticker}: {exit_signal.reason}")
                    await self._exit_position(ticker, position, exit_signal)

            except Exception as e:
                logger.error(f"Error managing position {ticker}: {e}")

    def _check_exit_legacy(self, position: Dict, current_price: int):
        """Check exit using legacy strategy."""
        entry_price = position.get("entry_price", 50)
        return self.strategy.should_exit_position(
            entry_price_cents=entry_price,
            current_price_cents=current_price,
            side=position["side"],
        )

    async def _check_exit_multi(self, position: Dict, current_price: int, market_data: Dict):
        """Check exit using strategy manager."""
        strategy_name = position.get("strategy", "mean_reversion")
        state = self.strategy_manager._strategies.get(strategy_name)

        if not state:
            # Fallback to first active strategy
            for s in self.strategy_manager._strategies.values():
                if s.enabled:
                    state = s
                    break

        if state:
            return await state.strategy.check_exit(
                position=position,
                current_price=current_price,
                market_data=market_data,
            )
        return None

    async def _exit_position(
        self,
        ticker: str,
        position: Dict,
        exit_signal: Any,
    ) -> None:
        """Exit a position."""
        try:
            # Create sell order
            side = position["side"]
            contracts = position["contracts"]

            order = await self.client.create_limit_order(
                ticker=ticker,
                side=side,
                action="sell",
                count=contracts,
                price_cents=exit_signal.current_price_cents,
            )

            # Update journal
            if trade_id := position.get("trade_id"):
                pnl = self.journal.close_trade(
                    trade_id=trade_id,
                    exit_price_cents=exit_signal.current_price_cents,
                    exit_order_id=order.get("order_id"),
                    exit_reason=exit_signal.exit_type,
                )

                # Record in risk management
                self.risk.record_trade_result(
                    ticker=ticker,
                    profit_loss_cents=pnl,
                    position_size_dollars=contracts,
                )

            # Remove from tracking
            del self.open_positions[ticker]

            # Notify strategy manager
            if self.strategy_manager:
                self.strategy_manager.record_position_close(ticker)

            # Evaluate strategy health after trade closes
            strategy_name = position.get("strategy", "mean_reversion")
            if self.performance_tracker:
                health = self.performance_tracker.evaluate_health(strategy_name)
                if health.health_status == "critical" and self.performance_tracker.auto_disable:
                    logger.warning(
                        f"Strategy {strategy_name} CRITICAL — "
                        f"auto-disable would trigger (disabled by config)"
                    )
                elif health.health_status != "healthy":
                    logger.warning(
                        f"Strategy {strategy_name}: {health.health_status} | "
                        f"blended EV={health.blended_ev_cents:.2f}c, "
                        f"confidence={health.confidence:.1%}"
                    )

            logger.info(
                f"Exited {ticker}: {exit_signal.exit_type} | "
                f"P&L: {exit_signal.pnl_cents:+d}c"
            )

        except Exception as e:
            logger.error(f"Failed to exit position {ticker}: {e}")

    async def _scan_and_trade_legacy(self) -> None:
        """Scan for opportunities using legacy single strategy."""
        # Get markets
        markets = await self.client.get_markets(
            series_ticker=self.config.market_series,
            status="open",
        )

        if not markets:
            logger.debug("No open markets found")
            return

        # Find opportunities
        opportunities = self.strategy.find_opportunities(
            markets=markets,
            existing_positions=set(self.open_positions.keys()),
        )

        if not opportunities:
            logger.debug("No trading opportunities found")
            return

        # Try to execute best opportunity
        for opp in opportunities[:3]:  # Check top 3
            if await self._execute_opportunity_legacy(opp):
                break  # One trade per cycle

    async def _scan_and_trade_multi(self) -> None:
        """Scan for opportunities using strategy manager."""
        # Scan all strategies
        opportunities = await self.strategy_manager.scan_all_opportunities(
            existing_positions=self.open_positions,
        )

        if not opportunities:
            logger.debug("No trading opportunities found")
            return

        # Rank and filter
        ranked = self.strategy_manager.rank_opportunities(opportunities)

        # Try to execute best opportunity
        for opp in ranked[:3]:  # Check top 3
            if await self._execute_opportunity_multi(opp):
                break  # One trade per cycle

    async def _execute_opportunity_legacy(self, opp) -> bool:
        """Execute opportunity using legacy strategy."""
        ticker = opp.ticker

        # Final risk check
        risk_check = self.risk.check_trade_allowed(
            ticker=ticker,
            position_size=self.config.max_position_size,
        )

        if not risk_check["allowed"]:
            logger.debug(f"Opportunity {ticker} blocked: {risk_check['reasons']}")
            return False

        # Calculate position size
        stats = self.strategy.get_historical_stats()
        size_result = self.risk.calculate_position_size(
            win_rate=stats["win_rate"],
            avg_win_cents=stats["avg_win_cents"],
            avg_loss_cents=stats["avg_loss_cents"],
            ticker=ticker,
        )

        contracts = size_result["contracts"]
        if contracts < 1:
            logger.debug(f"Position size too small for {ticker}: {contracts}")
            return False

        return await self._place_trade(ticker, opp, contracts, "mean_reversion")

    async def _execute_opportunity_multi(self, opp) -> bool:
        """Execute opportunity using strategy manager."""
        ticker = opp.ticker
        strategy_name = opp.strategy_name

        # Get allocated position size for this strategy
        max_size = self.strategy_manager.get_position_size_for_strategy(strategy_name)

        # Final risk check
        risk_check = self.risk.check_trade_allowed(
            ticker=ticker,
            position_size=max_size,
        )

        if not risk_check["allowed"]:
            logger.debug(f"Opportunity {ticker} blocked: {risk_check['reasons']}")
            return False

        # Get strategy for stats
        state = self.strategy_manager._strategies.get(strategy_name)
        if not state:
            return False

        stats = state.strategy.get_historical_stats()
        size_result = self.risk.calculate_position_size(
            win_rate=stats["win_rate"],
            avg_win_cents=stats["avg_win_cents"],
            avg_loss_cents=stats["avg_loss_cents"],
            ticker=ticker,
        )

        contracts = size_result["contracts"]
        if contracts < 1:
            logger.debug(f"Position size too small for {ticker}: {contracts}")
            return False

        return await self._place_trade(ticker, opp, contracts, strategy_name)

    async def _place_trade(
        self,
        ticker: str,
        opp,
        contracts: int,
        strategy_name: str,
    ) -> bool:
        """Place a trade and record it."""
        try:
            # In dry-run mode, log but don't execute
            if self.dry_run:
                logger.info(
                    f"[DRY RUN] Would execute: {ticker} | {opp.side} {contracts} @ {opp.entry_price_cents}c | "
                    f"Strategy: {strategy_name} | Score: {opp.score:.1f} | {opp.reasoning}"
                )
                return True

            # Place limit order
            order = await self.client.create_limit_order(
                ticker=ticker,
                side=opp.side,
                action="buy",
                count=contracts,
                price_cents=opp.entry_price_cents,
            )

            # Log trade
            trade_id = self.journal.log_trade(
                market_ticker=ticker,
                side=opp.side,
                action="buy",
                contracts=contracts,
                price_cents=opp.entry_price_cents,
                order_id=order.get("order_id"),
                reasoning=opp.reasoning,
                strategy=strategy_name,
            )

            # Track position
            self.open_positions[ticker] = {
                "trade_id": trade_id,
                "order_id": order.get("order_id"),
                "side": opp.side,
                "contracts": contracts,
                "entry_price": opp.entry_price_cents,
                "strategy": strategy_name,
            }

            # Record position open in risk management
            self.risk.record_position_open(ticker, float(contracts))

            # Notify strategy manager
            if self.strategy_manager:
                self.strategy_manager.record_position_open(ticker, strategy_name)

            logger.info(
                f"Trade executed: {ticker} | {opp.side} {contracts} @ {opp.entry_price_cents}c | "
                f"Strategy: {strategy_name} | Score: {opp.score:.1f} | {opp.reasoning}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to execute trade {ticker}: {e}")
            return False

    async def _wait_for_next_day(self) -> None:
        """Wait until next trading day or shutdown."""
        # Calculate time until midnight
        now = datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now.hour >= 0:
            midnight += timedelta(days=1)

        seconds_until_midnight = (midnight - now).total_seconds()

        logger.info(f"Waiting {seconds_until_midnight/3600:.1f} hours until next day")

        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(),
                timeout=seconds_until_midnight,
            )
        except asyncio.TimeoutError:
            # New day, reset daily stats
            self.risk.reset_daily_stats()


async def main():
    """Main entry point for command-line execution."""
    try:
        config = load_config()

        # Validate credentials
        valid, error = config.validate_credentials()
        if not valid:
            logger.error(f"Configuration error: {error}")
            logger.info(
                "Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH environment variables"
            )
            sys.exit(1)

        bot = KalshiTradingBot(config)
        await bot.start()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
