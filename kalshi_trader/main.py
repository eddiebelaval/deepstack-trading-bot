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
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .command_processor import CommandProcessor
from .captains_log import CaptainsLog, NarrationEvent, EventPriority
from .telegram_bridge import TelegramBridge
from .config import KalshiConfig, load_config, get_strategy_configs, load_yaml_config, CryExcConfig
from .trade_analyzer import TradeAnalyzer
from .dashboard_sync import DashboardSync
from .heartbeat import HeartbeatEngine
from .health_monitor import HealthMonitor
from .kalshi_client import AuthenticatedKalshiClient
from .deepstack_integration import DeepStackIntegration
from .journal import TradeJournal
from .market_governor import GovernanceEngine, MarketSnapshot
from .performance_tracker import PerformanceTracker
from .exceptions import (
    KalshiTradingError,
    DailyLossLimitHit,
    RiskLimitExceeded,
)

# Configure logging with file rotation
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    datefmt=_LOG_DATEFMT,
)

# Add rotating file handler (10 MB max, keep 3 backups)
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
from logging.handlers import RotatingFileHandler
_file_handler = RotatingFileHandler(
    _LOG_DIR / "deepstack.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
logging.getLogger().addHandler(_file_handler)

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
        paper_trade: bool = False,
    ):
        """
        Initialize trading bot.

        Args:
            config: KalshiConfig (loads from env if not provided)
            use_strategy_manager: Use multi-strategy mode (default: False for backward compat)
            strategy_configs: Custom strategy configs (overrides YAML)
            dry_run: If True, scan for opportunities but don't execute trades
            paper_trade: If True, simulate fills and write journal entries (no real orders)
        """
        self.config = config or load_config()
        self.use_strategy_manager = use_strategy_manager
        self.strategy_configs = strategy_configs
        self.dry_run = dry_run
        self.paper_trade = paper_trade

        self.client: Optional[AuthenticatedKalshiClient] = None
        self.risk: Optional[DeepStackIntegration] = None
        self.journal: Optional[TradeJournal] = None
        self.performance_tracker: Optional[PerformanceTracker] = None
        self.trade_analyzer: Optional[TradeAnalyzer] = None
        self.dashboard: Optional[DashboardSync] = None
        self.command_processor: Optional[CommandProcessor] = None

        # Strategy handling
        self.strategy = None  # Legacy single strategy
        self.strategy_manager = None  # Multi-strategy manager
        self.market = None  # Market adapter for StrategyManager

        # Market governance engine (optional, regime-aware strategy routing)
        self.market_governor: Optional[GovernanceEngine] = None

        # Captain's Log narration engine (optional, enabled via config)
        self.captains_log: Optional[CaptainsLog] = None

        # CryExc real-time exchange data bridge (optional, enabled via config)
        self._cryexc_bridge = None

        # IBKR market adapter (optional, enabled via config)
        self._ibkr_market = None

        # Lexicon order router (Phase 2, routes signals to IBKR paper trades)
        self._lexicon_order_router = None

        # Health monitor (self-healing watchdog)
        self.health_monitor: Optional[HealthMonitor] = None

        # Telegram bridge (two-way conversational interface)
        self.telegram_bridge: Optional[TelegramBridge] = None

        # Heartbeat engine (hybrid self-regulation)
        self.heartbeat: Optional[HeartbeatEngine] = None

        self._running = False
        self._paused = False
        self._shutdown_event = asyncio.Event()

        # Track open positions
        self.open_positions: Dict[str, Dict[str, Any]] = {}

        # Cache of last scanned market data for governance feed (cold-start fix)
        self._last_scanned_markets: List[Dict[str, Any]] = []

        # Per-strategy dynamic Kelly fractions (prevents last-strategy-wins bug)
        self._dynamic_kelly_fractions: Dict[str, float] = {}

        # Auto-disable: track consecutive critical cycles per strategy
        self._critical_cycle_counts: Dict[str, int] = {}
        self._auto_disabled_strategies: set = set()
        self._latest_health: Dict[str, Any] = {}

        # Hard circuit breakers per strategy (independent of health evaluation)
        # Structure: {strategy_name: {consecutive_losses, peak_pnl_cents, total_pnl_cents}}
        self._strategy_circuit_breakers: Dict[str, Dict[str, Any]] = {}

        # Strategies explicitly disabled in config.yaml — Supabase overrides
        # cannot re-enable these (config is authoritative on startup).
        # Built from strategy_configs; empty set if no configs provided.
        self._config_disabled_strategies: set = set()
        if strategy_configs:
            for cfg in strategy_configs:
                if not cfg.get("enabled", True):
                    self._config_disabled_strategies.add(cfg["name"])

        # Research lab milestone triggers — generates assessment briefs at key trade counts
        self._lab_milestones = [25, 76, 125, 200]
        self._lab_milestones_triggered: set = set()

        # Self-regulation engine state
        self._consecutive_empty_scans: int = 0
        self._regulation_adjustments: List[str] = []  # Log of adjustments made
        self._original_min_volume: Optional[int] = None  # Stash original for reset
        self._original_min_edge: Optional[float] = None
        self._original_max_hours: Optional[float] = None
        self._profit_protection_active: bool = False
        self._daily_reflection_done: bool = False

        # Round 7 P0 (Sullivan) + Round 8 P0 (Vasquez): Escalating inaction alerting.
        # Track consecutive zero-opportunity cycles per enabled strategy.
        # Tiered severity: WARNING at 50 cycles (~25 min), ERROR at 120 (~1h),
        # CRITICAL at 240 (~2h). Re-alerts every 100 cycles after initial threshold.
        self._inaction_cycles: Dict[str, int] = {}
        self._inaction_alert_threshold: int = 50  # WARNING at ~25 min
        self._inaction_error_threshold: int = 120  # ERROR at ~1h
        self._inaction_critical_threshold: int = 240  # CRITICAL at ~2h
        self._inaction_repeat_interval: int = 100  # Re-alert every ~50 min
        self._inaction_last_alert_cycle: Dict[str, int] = {}  # Track last alert cycle per strategy

        # Auto re-enable: track when each strategy was auto-disabled
        self._auto_disabled_at: Dict[str, datetime] = {}
        self._reenable_cooldown_hours: int = 6

        # Periodic adaptive threshold refresh counter
        self._trading_cycle_count: int = 0
        self._adaptive_refresh_interval: int = 100  # cycles (~30 min at 18s interval)
        # Apply 30% tighter Kelly on re-enable to limit exposure during probation
        self._reenable_tighter_factor: float = 0.7

        # Daily review: track last review date to trigger once per day
        self._last_daily_review_date: Optional[str] = None

        # Captain's Log: track balance for >1% change detection
        self._last_captains_log_balance: Optional[float] = None

        # Claude analysis: track last analysis time (run every 30 min)
        self._last_analysis_time: Optional[datetime] = None
        self._analysis_interval_minutes: int = 30

        logger.info(
            f"KalshiTradingBot initialized | "
            f"Series: {self.config.market_series} | "
            f"Max position: ${self.config.max_position_size} | "
            f"Daily loss limit: ${self.config.daily_loss_limit} | "
            f"Multi-strategy: {use_strategy_manager} | "
            f"Dry-run: {dry_run} | Paper-trade: {paper_trade}"
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

            # Start all loops concurrently
            self._running = True
            command_task = asyncio.create_task(self._command_loop())
            trading_task = asyncio.create_task(self._trading_loop())
            health_task = asyncio.create_task(self._health_monitor_loop())

            # Start Telegram bridge polling (if credentials available)
            telegram_task = None
            if self.telegram_bridge and self.telegram_bridge.is_available:
                telegram_task = asyncio.create_task(self.telegram_bridge.start_polling())

            # Wait for trading loop to finish (others stop when _running=False)
            await trading_task
            tasks_to_cancel = [command_task, health_task]
            if telegram_task:
                tasks_to_cancel.append(telegram_task)
            for task in tasks_to_cancel:
                task.cancel()
                try:
                    await task
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

        # 2b. Portfolio drawdown protection — high-water mark loaded after
        # performance_tracker init (see step 5d below). Temporarily set from API.
        self._initial_balance = account_balance
        self._portfolio_halted = False

        # 3. Initialize risk management
        self.risk = DeepStackIntegration(self.config, account_balance)

        # Paper trade mode: disable emotional firewall checks.
        # We need unbiased signal data, not behavioral throttling.
        if self.paper_trade:
            self.risk.firewall.enable_all_checks = False
            logger.info("[PAPER] Emotional firewall disabled for unbiased data collection")

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
        self._apply_adaptive_thresholds()

        # 5b-ii. Restore persistent state from SQLite (Round 2 P0: survive restarts)
        stored_hwm = self.performance_tracker.load_bot_state("high_water_mark_balance")
        if stored_hwm is not None and stored_hwm > account_balance:
            self._initial_balance = stored_hwm
            logger.info(
                f"Restored high-water mark: ${stored_hwm:.2f} "
                f"(current: ${account_balance:.2f}, drawdown: "
                f"{(stored_hwm - account_balance) / stored_hwm:.1%})"
            )
        else:
            # New high-water mark — persist it
            self.performance_tracker.save_bot_state(
                "high_water_mark_balance", account_balance
            )

        # Restore circuit breaker state (Round 2 P0: breakers survive restarts)
        persisted_breakers = self.performance_tracker.load_all_circuit_breakers()
        if persisted_breakers:
            self._strategy_circuit_breakers = persisted_breakers
            logger.info(
                f"Restored circuit breaker state for "
                f"{len(persisted_breakers)} strategies"
            )

        # 5c. Initialize Claude analysis (optional, enabled via config)
        yaml_cfg = load_yaml_config()
        if yaml_cfg and yaml_cfg.analysis.enabled:
            analysis_dict = yaml_cfg.analysis.model_dump()
            self.trade_analyzer = TradeAnalyzer({"analysis": analysis_dict})
            if self.trade_analyzer.is_available:
                logger.info(
                    "Trade analyzer initialized (model=%s)",
                    analysis_dict.get("model"),
                )
            else:
                logger.warning("Trade analyzer enabled but ANTHROPIC_API_KEY not set")
                self.trade_analyzer = None
        else:
            logger.info("Trade analyzer disabled (analysis.enabled=false)")

        # 5d. Initialize market governance engine (optional)
        if yaml_cfg and yaml_cfg.governance.enabled:
            gov_cfg = yaml_cfg.governance
            self.market_governor = GovernanceEngine(
                db_path=self.config.journal_db_path,
                enabled=True,
                mode=gov_cfg.mode,
                lookback_periods=gov_cfg.lookback_periods,
                min_confidence=gov_cfg.min_confidence,
                fitness_min_trades=gov_cfg.fitness_min_trades,
                enable_threshold=gov_cfg.enable_threshold,
                disable_threshold=gov_cfg.disable_threshold,
                bleed_window_hours=gov_cfg.bleed_window_hours,
                bleed_threshold_cents=gov_cfg.bleed_threshold_cents,
                bleed_slope_threshold=gov_cfg.bleed_slope_threshold,
                max_strategies_disabled_pct=gov_cfg.max_strategies_disabled_pct,
                reenable_cooldown_hours=gov_cfg.reenable_cooldown_hours,
            )
            logger.info("Market governor initialized (mode=%s)", gov_cfg.mode)

            # Attach LexiconSignalGenerator if enabled (Phase 2)
            if yaml_cfg.lexicon_signals.enabled:
                from .strategies.lexicon_signal_generator import LexiconSignalGenerator
                sig_config = yaml_cfg.lexicon_signals.model_dump()
                sig_gen = LexiconSignalGenerator(sig_config)
                self.market_governor.set_lexicon_signal_generator(sig_gen)
                logger.info("Lexicon signal generator attached to governance engine")
        else:
            logger.info("Market governor disabled (governance.enabled=false)")

        # 5e. Initialize Captain's Log narration engine (optional)
        self.config_yaml = yaml_cfg  # Store for later use
        if yaml_cfg and yaml_cfg.captains_log.enabled:
            self.captains_log = CaptainsLog(
                config=yaml_cfg.captains_log.model_dump(),
                dashboard_sync=None,  # Will be set after dashboard init
            )
            if self.captains_log.is_available:
                logger.info("Captain's Log enabled (will connect after dashboard init)")
            else:
                logger.warning("Captain's Log enabled but ANTHROPIC_API_KEY not set")
                self.captains_log = None
        else:
            logger.info("Captain's Log disabled (captains_log.enabled=false)")

        # 6. Initialize dashboard sync (Supabase, fire-and-forget)
        self.dashboard = DashboardSync()
        await self.dashboard.connect()

        # 6-post. Push fresh balance to dashboard on startup so the dashboard
        # always reflects the real Kalshi balance, even when the trading
        # loop hasn't run yet.
        await self.dashboard.push_balance_only(
            balance_cents=int(self._initial_balance * 100),
            available_balance_cents=int(self._initial_balance * 100),
            source="startup_sync",
        )
        logger.info(f"Startup balance synced to dashboard: ${self._initial_balance:.2f}")

        # 6a. Wire Captain's Log to dashboard sync and connect
        if self.captains_log:
            self.captains_log._dashboard = self.dashboard
            await self.captains_log.connect()
            self.captains_log.record_event(NarrationEvent(
                event_type="startup",
                priority=EventPriority.SIGNIFICANT,
                timestamp=datetime.now(timezone.utc),
                summary=(
                    f"Dae online. Balance: ${self.risk.account_balance:.2f}. "
                    f"{len(self.strategy_manager._strategies) if self.strategy_manager else 1} strategies loaded."
                ),
                strategy=None,
                metadata={},
            ))

        # 6b. Restore strategy enabled states from Supabase (persists user toggles across restarts)
        # Round 7 P0: config.yaml is authoritative in BOTH directions.
        # - Config says enabled=false → Supabase cannot re-enable (existing protection)
        # - Config says enabled=true  → Supabase cannot disable (NEW protection)
        # Only strategies with NO explicit config entry defer to Supabase state.
        if self.strategy_manager:
            overrides = await self.dashboard.get_strategy_overrides()
            restored = 0
            ignored_stale = 0
            for name, enabled in overrides.items():
                if name in self.strategy_manager._strategies:
                    state = self.strategy_manager._strategies[name]
                    # Round 7 P0: If config.yaml explicitly enables a strategy,
                    # do NOT allow stale Supabase overrides to disable it.
                    # This prevents the calibration_edge runtime-disabled bug.
                    if not enabled and name not in self._config_disabled_strategies:
                        # Strategy is config-enabled but Supabase says disabled.
                        # Config.yaml wins — ignore the stale override.
                        ignored_stale += 1
                        logger.warning(
                            f"Ignoring stale Supabase override for '{name}' "
                            f"(enabled=False) — config.yaml says enabled. "
                            f"Config is authoritative on startup."
                        )
                        continue
                    if state.enabled != enabled:
                        state.enabled = enabled
                        restored += 1
                        logger.info(f"Restored strategy '{name}' enabled={enabled} from dashboard")
            if restored:
                logger.info(f"Restored {restored} strategy toggle(s) from Supabase")
            if ignored_stale:
                logger.warning(
                    f"Ignored {ignored_stale} stale Supabase override(s) — "
                    f"config.yaml is authoritative on startup"
                )

        # 7. Initialize command processor (Supabase polling)
        self.command_processor = CommandProcessor(self)
        await self.command_processor.connect()

        # 8. Load existing positions
        await self._sync_positions()

        # 9. Initialize health monitor
        self.health_monitor = HealthMonitor(
            bot=self,
            db_path=self.config.journal_db_path,
        )
        logger.info("Health monitor initialized")

        # 10. Initialize Telegram bridge (two-way conversational interface)
        self.telegram_bridge = TelegramBridge(self)
        await self.telegram_bridge.connect()
        if self.telegram_bridge.is_available:
            logger.info("Telegram Bridge initialized")
        else:
            logger.info("Telegram Bridge disabled (no credentials)")

        # 10b. Initialize heartbeat engine (hybrid self-regulation)
        if yaml_cfg and yaml_cfg.heartbeat.enabled:
            heartbeat_dict = yaml_cfg.heartbeat.model_dump()
            self.heartbeat = HeartbeatEngine(self, heartbeat_dict)
            if self.telegram_bridge.is_available:
                self.heartbeat.set_telegram(self.telegram_bridge)
        else:
            self.heartbeat = None
            logger.info("Heartbeat engine disabled (heartbeat.enabled=false)")

        # 11. Update bot config to running
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

        # Populate _config_disabled_strategies if not already set from __init__
        if not self._config_disabled_strategies:
            for cfg in configs:
                if not cfg.get("enabled", True):
                    self._config_disabled_strategies.add(cfg["name"])

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

        # Create IBKR if enabled in config (stock trading)
        yaml_config = load_yaml_config()
        if yaml_config and yaml_config.ibkr.enabled:
            try:
                from markets import IBKRMarket

                ibkr_config = yaml_config.ibkr.model_dump()
                ibkr_market = IBKRMarket(ibkr_config)
                connected = await ibkr_market.connect()

                if connected:
                    markets_dict["ibkr"] = ibkr_market
                    self._ibkr_market = ibkr_market
                    logger.info(
                        f"IBKR market initialized: "
                        f"port={ibkr_config['port']}, "
                        f"watchlist={ibkr_config['watchlist']}"
                    )

                    # Attach LexiconOrderRouter for paper signal trading (Phase 2)
                    if ibkr_config.get("port") == 7497:  # Paper port only
                        from markets.ibkr import LexiconOrderRouter
                        self._lexicon_order_router = LexiconOrderRouter(
                            ibkr_market=ibkr_market,
                            max_order_value_cents=self.config.max_position_size * 100,
                        )
                        logger.info("LexiconOrderRouter attached (paper mode)")
                else:
                    logger.warning("IBKR connection failed — stock trading disabled")
            except Exception as e:
                logger.warning(f"Failed to initialize IBKR: {e}")

        # Create manager with config
        manager_config = {"strategies": configs}
        # Paper trading: raise position cap to accumulate more data for assessment
        max_positions = 50 if self.paper_trade else 10
        self.strategy_manager = StrategyManager(
            config=manager_config,
            markets=markets_dict,
            max_position_size=self.config.max_position_size,
            max_total_positions=max_positions,
            max_per_series=getattr(self.config, 'max_per_series', 2),
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
                # Inject bridge into strategy manager AND individual strategies.
                # _inject_market_clients() already ran during initialize() when
                # _cryexc_bridge was None, so we propagate directly here.
                if self.strategy_manager:
                    self.strategy_manager._cryexc_bridge = self._cryexc_bridge
                    for name, state in self.strategy_manager._strategies.items():
                        if hasattr(state.strategy, "_cryexc_bridge"):
                            state.strategy._cryexc_bridge = self._cryexc_bridge
                            logger.debug(f"CryExc bridge injected into {name}")

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

    def _apply_adaptive_thresholds(self) -> None:
        """Apply learned take_profit/stop_loss and dynamic Kelly to active strategies."""
        if not self.performance_tracker:
            return

        if self.strategy_manager:
            for name, state in self.strategy_manager._strategies.items():
                params = self.performance_tracker.get_adaptive_params(name)
                if params and hasattr(state.strategy, 'apply_adaptive_params'):
                    state.strategy.apply_adaptive_params(params)
                self._apply_dynamic_kelly(name)
        elif self.strategy and hasattr(self.strategy, 'apply_adaptive_params'):
            params = self.performance_tracker.get_adaptive_params("mean_reversion")
            if params:
                self.strategy.apply_adaptive_params(params)
            self._apply_dynamic_kelly("mean_reversion")

    def _check_lab_milestones(self) -> None:
        """Check if closed trade count has hit a research lab milestone.

        At milestones (25, 76, 125, 200 trades), generates an assessment
        brief and writes it to the research lab queue for expert evaluation.
        """
        if not self.journal:
            return

        stats = self.journal.get_trade_statistics()
        n = stats["total_trades"]

        for milestone in self._lab_milestones:
            if n >= milestone and milestone not in self._lab_milestones_triggered:
                self._lab_milestones_triggered.add(milestone)

                brief = self.journal.generate_assessment_brief(
                    milestone=f"n={milestone}",
                    paper_trade=self.paper_trade,
                )

                # Write to research lab queue
                lab_queue = Path.home() / "Development" / "id8" / "research-lab" / "queue"
                if lab_queue.exists():
                    brief_num = len(list(lab_queue.glob("*.md"))) + 1
                    brief_path = lab_queue / f"{brief_num:03d}-deepstack-empirical-n{milestone}.md"
                    brief_path.write_text(brief)
                    logger.info(
                        f"[LAB] Milestone n={milestone} reached! "
                        f"Assessment brief written to {brief_path}"
                    )
                else:
                    logger.warning(
                        f"[LAB] Milestone n={milestone} reached but lab queue not found at {lab_queue}"
                    )

                # Also log to Captain's Log
                if self.captains_log:
                    self.captains_log.record_event(NarrationEvent(
                        event_type="milestone",
                        priority=EventPriority.CRITICAL,
                        timestamp=datetime.now(timezone.utc),
                        summary=(
                            f"Research lab milestone: {n} closed trades. "
                            f"Assessment brief generated for expert panel review."
                        ),
                        metadata={"milestone": milestone, "total_trades": n, "paper_trade": self.paper_trade},
                    ))

    def _self_regulate(self) -> None:
        """Autonomous self-regulation engine.

        Observes the bot's own behavior and makes adjustments:
        - Empty funnel diagnosis: progressively relax filters when scans find nothing
        - Recovery: tighten filters back when opportunities flow
        - Profit protection: reduce risk when daily P&L is positive
        - Daily reflection: end-of-day self-assessment

        This is the bot's metacognitive loop — it thinks about its own performance
        and adjusts without human intervention.
        """
        if not self.strategy_manager:
            return

        # Get the calibration_edge strategy (primary active strategy)
        cal_state = self.strategy_manager._strategies.get("calibration_edge")
        if not cal_state or not cal_state.enabled:
            return

        strategy = cal_state.strategy

        # --- Phase 1: Funnel-aware diagnosis and targeted relaxation ---
        if self._consecutive_empty_scans > 0:
            # Stash originals on first adjustment
            if self._original_min_volume is None:
                self._original_min_volume = getattr(strategy, 'min_volume', 100)
                self._original_min_edge = getattr(strategy, 'min_edge', 3.0)
                self._original_max_hours = getattr(strategy, 'max_hours_to_expiry', 72)

            # Read funnel data to diagnose the bottleneck
            funnel = getattr(strategy, '_last_funnel', None)
            if funnel and self._consecutive_empty_scans >= 2:
                # Identify the biggest drop-off in the funnel
                steps = [
                    ("tradeable", funnel.get("tradeable", 0), "min_volume"),
                    ("expiry_pass", funnel.get("expiry_pass", 0), "max_hours_to_expiry"),
                    ("has_bid_ask", funnel.get("has_bid_ask", 0), "bid_ask"),
                    ("edge_qualifying", funnel.get("edge_qualifying", 0), "min_edge"),
                ]
                prev = funnel.get("not_held", 0)  # Start after "not held" (can't adjust this)
                worst_step = None
                worst_drop = 0
                for step_name, step_count, param in steps:
                    drop = prev - step_count
                    if drop > worst_drop:
                        worst_drop = drop
                        worst_step = (step_name, param, prev, step_count)
                    prev = step_count

                if worst_step:
                    step_name, param, before, after = worst_step
                    logger.info(
                        f"[SELF-REG] Funnel bottleneck: '{step_name}' ({before} → {after}, "
                        f"drop={before - after}). Targeting: {param}"
                    )

                    # Adjust the bottleneck parameter immediately
                    if param == "max_hours_to_expiry":
                        current_hours = getattr(strategy, 'max_hours_to_expiry', 72)
                        # Aggressive relaxation: double the window each cycle, cap at 720h (30 days)
                        new_hours = min(720, int(current_hours * 1.5))
                        if new_hours > current_hours:
                            strategy.max_hours_to_expiry = new_hours
                            adjustment = f"[SELF-REG] Extended max_hours_to_expiry: {current_hours} → {new_hours}h (bottleneck: {before}→{after})"
                            logger.info(adjustment)
                            self._regulation_adjustments.append(adjustment)

                    elif param == "min_volume":
                        current_vol = getattr(strategy, 'min_volume', 100)
                        new_vol = max(10, current_vol // 2)
                        if new_vol < current_vol:
                            strategy.min_volume = new_vol
                            adjustment = f"[SELF-REG] Relaxed min_volume: {current_vol} → {new_vol} (bottleneck: {before}→{after})"
                            logger.info(adjustment)
                            self._regulation_adjustments.append(adjustment)

                    elif param == "min_edge":
                        current_edge = getattr(strategy, 'min_edge', 3.0)
                        new_edge = max(1.0, current_edge - 1.0)
                        if new_edge < current_edge:
                            strategy.min_edge = new_edge
                            adjustment = f"[SELF-REG] Reduced min_edge: {current_edge}c → {new_edge}c (bottleneck: {before}→{after})"
                            logger.info(adjustment)
                            self._regulation_adjustments.append(adjustment)

            # Fallback: if no funnel data, use tier escalation
            elif not funnel and self._consecutive_empty_scans >= 5:
                current_hours = getattr(strategy, 'max_hours_to_expiry', 72)
                if current_hours < 336:
                    strategy.max_hours_to_expiry = min(336, int(current_hours * 1.5))
                    logger.info(f"[SELF-REG] Blind escalation: max_hours {current_hours} → {strategy.max_hours_to_expiry}h")

            # Log periodic self-reflection during drought
            if self._consecutive_empty_scans % 5 == 0 and self._consecutive_empty_scans > 0:
                logger.warning(
                    f"[SELF-REG] Reflection: {self._consecutive_empty_scans} consecutive empty scans. "
                    f"Current params: min_vol={getattr(strategy, 'min_volume', '?')}, "
                    f"min_edge={getattr(strategy, 'min_edge', '?')}c, "
                    f"max_hours={getattr(strategy, 'max_hours_to_expiry', '?')}h. "
                    f"Adjustments made: {len(self._regulation_adjustments)}"
                )

        # --- Phase 2: Recovery — tighten back when opportunities flow ---
        elif self._consecutive_empty_scans == 0 and self._original_min_volume is not None:
            # Gradually restore original values (don't snap back — tighten by 10% per cycle)
            current_vol = getattr(strategy, 'min_volume', 25)
            if current_vol < self._original_min_volume:
                new_vol = min(self._original_min_volume, int(current_vol * 1.1) + 1)
                strategy.min_volume = new_vol
                if new_vol >= self._original_min_volume:
                    logger.info(f"[SELF-REG] Restored min_volume to original: {self._original_min_volume}")

            current_edge = getattr(strategy, 'min_edge', 1.0)
            if self._original_min_edge and current_edge < self._original_min_edge:
                new_edge = min(self._original_min_edge, current_edge + 0.1)
                strategy.min_edge = new_edge
                if new_edge >= self._original_min_edge:
                    logger.info(f"[SELF-REG] Restored min_edge to original: {self._original_min_edge}c")

            current_hours = getattr(strategy, 'max_hours_to_expiry', 168)
            if self._original_max_hours and current_hours > self._original_max_hours:
                new_hours = max(self._original_max_hours, current_hours - 6)
                strategy.max_hours_to_expiry = new_hours
                if new_hours <= self._original_max_hours:
                    logger.info(f"[SELF-REG] Restored max_hours to original: {self._original_max_hours}h")

            # Reset originals when fully restored
            all_restored = (
                getattr(strategy, 'min_volume', 0) >= (self._original_min_volume or 0) and
                getattr(strategy, 'min_edge', 0) >= (self._original_min_edge or 0) and
                getattr(strategy, 'max_hours_to_expiry', 999) <= (self._original_max_hours or 999)
            )
            if all_restored:
                self._original_min_volume = None
                self._original_min_edge = None
                self._original_max_hours = None

        # --- Phase 3: Profit protection ---
        if self.risk:
            daily_stats = self.risk.get_daily_stats()
            daily_pnl = daily_stats.get("daily_pnl", 0)

            # When daily P&L is positive and we've made 3+ trades,
            # reduce max position size to protect gains
            if daily_pnl > 0 and daily_stats.get("daily_trades", 0) >= 3:
                if not self._profit_protection_active:
                    self._profit_protection_active = True
                    logger.info(
                        f"[SELF-REG] Profit protection ACTIVATED: daily P&L=${daily_pnl:.2f}. "
                        f"Reducing max position to protect gains."
                    )
            elif daily_pnl <= 0:
                if self._profit_protection_active:
                    self._profit_protection_active = False
                    logger.info(f"[SELF-REG] Profit protection DEACTIVATED: daily P&L=${daily_pnl:.2f}")

        # --- Phase 4: Daily reflection ---
        today = datetime.now().strftime("%Y-%m-%d")
        if hasattr(self, '_last_reflection_date') and self._last_reflection_date == today:
            return  # Already reflected today

        # Generate reflection at end of day (after 23:00)
        if datetime.now().hour >= 23 and not self._daily_reflection_done:
            self._daily_reflection_done = True
            self._last_reflection_date = today
            self._generate_daily_reflection()

    def _generate_daily_reflection(self) -> None:
        """Generate end-of-day self-assessment.

        Writes a reflection to the log analyzing today's performance,
        what worked, what didn't, and what to adjust tomorrow.
        """
        if not self.journal:
            return

        stats = self.journal.get_trade_statistics(
            start_date=date.today(),
            end_date=date.today(),
        )

        n_trades = stats["total_trades"]
        win_rate = stats["win_rate"]
        total_pnl = stats["total_pnl_cents"]
        profit_factor = stats["profit_factor"]

        # Self-assessment
        if n_trades == 0:
            assessment = "No trades executed. Likely a market coverage or filter issue."
            action = "Will continue relaxing filters if drought persists."
        elif total_pnl > 0:
            assessment = f"Profitable day: {n_trades} trades, WR={win_rate:.0%}, PF={profit_factor:.2f}."
            action = "Maintain current parameters. Engage profit protection on next session."
        elif win_rate >= 0.5:
            assessment = f"Positive win rate ({win_rate:.0%}) but negative P&L. Winners too small or losers too large."
            action = "Consider tightening stop-loss or widening take-profit targets."
        else:
            assessment = f"Losing day: WR={win_rate:.0%}, P&L={total_pnl:+d}c. Strategy may need parameter adjustment."
            action = "Will tighten entry criteria (raise min_edge) if losses continue."

        reflection = (
            f"[SELF-REG] Daily Reflection ({date.today()}): "
            f"{assessment} "
            f"Trades: {n_trades}, P&L: {total_pnl:+d}c (${total_pnl/100:+.2f}), "
            f"Adjustments today: {len(self._regulation_adjustments)}. "
            f"Plan: {action}"
        )

        logger.info(reflection)

        # Reset daily state
        self._regulation_adjustments.clear()
        self._daily_reflection_done = False  # Reset for next day

    def _apply_dynamic_kelly(self, strategy_name: str) -> None:
        """Calculate and apply Kelly fraction from blended performance stats.

        Uses the Kelly Criterion: f* = p - q/b
        where p = blended win rate, q = 1-p, b = avg_win/avg_loss.
        Only overrides config when learning_confidence > 0.3 (enough observed data).
        Clamped to [0.05, 0.5] to prevent ruin and maintain learning signal.
        """
        if not self.performance_tracker:
            return

        stats = self.performance_tracker.get_blended_stats(strategy_name)
        prior = self.performance_tracker.get_prior(strategy_name)

        # Calculate learning confidence: n / (n + k)
        k = prior.prior_strength if prior else self.performance_tracker.prior_strength
        n = self.performance_tracker._get_effective_trade_count(strategy_name)
        learning_confidence = n / (n + k) if (n + k) > 0 else 0.0

        if learning_confidence <= 0.3:
            logger.debug(
                f"[{strategy_name}] Dynamic Kelly skipped: "
                f"learning_confidence={learning_confidence:.2f} <= 0.3"
            )
            return

        blended_win_rate = stats["win_rate"]
        avg_win = stats["avg_win_cents"]
        avg_loss = stats["avg_loss_cents"]

        if avg_loss <= 0:
            logger.warning(f"[{strategy_name}] Dynamic Kelly skipped: avg_loss={avg_loss}")
            return

        win_loss_ratio = avg_win / avg_loss
        raw_kelly = blended_win_rate - ((1 - blended_win_rate) / win_loss_ratio)
        clamped_kelly = max(0.005, min(0.05, raw_kelly))

        old_kelly = self._dynamic_kelly_fractions.get(strategy_name, self.config.kelly_fraction)
        self._dynamic_kelly_fractions[strategy_name] = clamped_kelly

        logger.info(
            f"[{strategy_name}] Dynamic Kelly: {old_kelly:.3f} -> {clamped_kelly:.3f} "
            f"(raw={raw_kelly:.3f}, win_rate={blended_win_rate:.3f}, "
            f"W/L={win_loss_ratio:.2f}, confidence={learning_confidence:.2f})"
        )

    async def _shutdown(self) -> None:
        """Clean shutdown of all components."""
        logger.info("Shutting down...")

        try:
            # Record shutdown in Captain's Log
            if self.captains_log:
                self.captains_log.record_event(NarrationEvent(
                    event_type="shutdown",
                    priority=EventPriority.SIGNIFICANT,
                    timestamp=datetime.now(timezone.utc),
                    summary="Dae shutting down.",
                    strategy=None,
                    metadata={},
                ))
                # Force narrate the shutdown event
                bot_state = {
                    "balance": self.risk.account_balance if self.risk else 0,
                    "daily_pnl": self.risk.get_daily_stats()["daily_pnl"] if self.risk else 0,
                    "open_positions": len(self.open_positions),
                    "regime": "shutdown",
                    "active_strategies": [],
                }
                await self.captains_log.narrate_if_ready(bot_state)
                await self.captains_log.disconnect()

            # Push shutdown state to Supabase
            if self.command_processor:
                await self.command_processor.update_mode("stopped")
            if self.dashboard:
                await self.dashboard.push_log("Bot shutting down", level="WARNING", strategy="system")

            # Push final balance so dashboard stays fresh while bot is off
            if self.client and self.dashboard:
                try:
                    balance = await self.client.get_balance()
                    await self.dashboard.push_balance_only(
                        balance_cents=int(balance["available"] * 100),
                        available_balance_cents=int(balance["available"] * 100),
                        source="shutdown_sync",
                    )
                    logger.info(f"Shutdown balance synced: ${balance['available']:.2f}")
                except Exception:
                    pass  # Best-effort — don't block shutdown

            # Disconnect Telegram bridge
            if self.telegram_bridge:
                await self.telegram_bridge.disconnect()

            # Close heartbeat engine
            if self.heartbeat:
                await self.heartbeat.close()

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

            # Generate daily review (per-strategy metrics, patterns, blend comparison)
            if self.performance_tracker:
                review = self.performance_tracker.generate_daily_review()
                if review["total_trades"] > 0:
                    parts = [
                        f"Daily Review: {review['total_trades']} trades, "
                        f"${review['total_pnl_cents'] / 100:.2f} P&L",
                    ]
                    for strat, metrics in review["strategies"].items():
                        parts.append(
                            f"{strat}: {metrics['wins']}W/{metrics['losses']}L "
                            f"(${metrics['total_pnl_cents'] / 100:.2f})"
                        )
                    for pattern in review["patterns"]:
                        parts.append(f"Pattern: {pattern}")

                    if self.dashboard:
                        await self.dashboard.push_log(
                            " | ".join(parts),
                            level="INFO",
                            strategy="daily_review",
                        )
                    logger.info(f"Daily review: {' | '.join(parts)}")

            # Close trade analyzer
            if self.trade_analyzer:
                await self.trade_analyzer.close()

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

    async def _health_monitor_loop(self) -> None:
        """Health monitor loop — runs alongside trading and command loops."""
        if not self.health_monitor:
            return
        try:
            await self.health_monitor.run_loop(self._shutdown_event)
        except asyncio.CancelledError:
            logger.info("Health monitor loop cancelled")
        except Exception as e:
            logger.error(f"Health monitor loop crashed: {e}", exc_info=True)

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

        # 2. Check for strategies that need auto-disabling
        await self._check_auto_disable()

        # 2b. Evaluate health + hard circuit breakers (runs after _apply_adaptive_thresholds)
        await self._check_strategy_health_and_breakers()

        # 2c. Check if any auto-disabled strategies can be re-enabled after cooldown
        await self._check_auto_reenable()

        # 2d. Run daily review on date rollover (populates daily_reviews table)
        await self._run_daily_review()

        # 2e. Run AI analysis on timer (every 30 min when enabled)
        await self._run_ai_analysis()

        # 2f. Run market governance (regime detection + strategy routing)
        await self._run_governance()

        # 2g. Periodic adaptive threshold refresh (every ~100 cycles)
        self._trading_cycle_count += 1
        if self._trading_cycle_count % self._adaptive_refresh_interval == 0:
            self._apply_adaptive_thresholds()
            logger.info(
                f"Periodic adaptive threshold refresh (cycle {self._trading_cycle_count})"
            )

        # Skip market scanning if paused
        if self._paused:
            logger.debug("Bot paused — skipping market scan")
            return

        # 2a. Portfolio-level drawdown check (P0-2: prevents account destruction)
        # Round 2 P0: Update high-water mark if balance has increased
        current_balance = self.risk.account_balance
        if current_balance > self._initial_balance:
            self._initial_balance = current_balance
            if self.performance_tracker:
                self.performance_tracker.save_bot_state(
                    "high_water_mark_balance", current_balance
                )

        if current_balance <= self.config.min_balance_floor:
            if not self._portfolio_halted:
                logger.critical(
                    f"PORTFOLIO HALT: Balance ${current_balance:.2f} below "
                    f"floor ${self.config.min_balance_floor:.2f}. All trading stopped."
                )
                self._portfolio_halted = True
            return

        if self._initial_balance > 0:
            drawdown_pct = (self._initial_balance - current_balance) / self._initial_balance
            if drawdown_pct >= self.config.max_portfolio_drawdown_pct:
                if not self._portfolio_halted:
                    logger.critical(
                        f"PORTFOLIO HALT: Drawdown {drawdown_pct:.1%} exceeds "
                        f"limit {self.config.max_portfolio_drawdown_pct:.0%}. "
                        f"Balance: ${current_balance:.2f} (started: ${self._initial_balance:.2f}). "
                        f"All trading stopped."
                    )
                    self._portfolio_halted = True
                return

        # 2b. Check risk limits
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

        # 5. Captain's Log — narrate if conditions met
        bot_state = {
            "balance": self.risk.account_balance,
            "daily_pnl": self.risk.get_daily_stats()["daily_pnl"],
            "open_positions": len(self.open_positions),
            "regime": getattr(self, '_current_regime', 'unknown'),
            "active_strategies": [
                name for name, s in self.strategy_manager._strategies.items() if s.enabled
            ] if self.strategy_manager else [],
        }
        if self.captains_log:
            await self.captains_log.narrate_if_ready(bot_state)

        # 6. Heartbeat — deterministic checks + periodic AI heartbeat
        if self.heartbeat:
            await self.heartbeat.tick(bot_state)

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
            cash_cents = int(balance["available"] * 100)

            # Compute mark-to-market portfolio value and enrich position data
            # with current prices and market titles for the dashboard.
            market_value_cents = 0
            enriched_positions = []
            for ticker, position in self.open_positions.items():
                try:
                    market = await self.client.get_market(ticker)
                    last_price = market.get("last_price", 50)
                    title = market.get("title", "")
                    contracts = position["contracts"]
                    side = position["side"]

                    if side == "yes":
                        pos_value = contracts * last_price
                    else:
                        pos_value = contracts * (100 - last_price)
                    market_value_cents += pos_value

                    # Compute avg entry from market_exposure if available
                    exposure = position.get("market_exposure", 0)
                    avg_entry = round(exposure / contracts) if contracts > 0 and exposure > 0 else None

                    enriched_positions.append({
                        "ticker": ticker,
                        "market_title": title,
                        "side": side,
                        "contracts": contracts,
                        "position": contracts if side == "yes" else -contracts,
                        "total_traded": position.get("total_traded", 0),
                        "market_exposure": exposure,
                        "realized_pnl": position.get("realized_pnl", 0),
                        "fees_paid": position.get("fees_paid", 0),
                        "resting_orders_count": position.get("resting_orders_count", 0),
                        "current_price": last_price,
                        "market_value_cents": pos_value,
                        "avg_entry_price_cents": avg_entry,
                        "volume_24h": market.get("volume_24h", 0),
                        "open_interest": market.get("open_interest", 0),
                        "previous_price": market.get("previous_price"),
                        "last_updated_ts": position.get("last_updated_ts"),
                    })
                except Exception:
                    pass  # Skip positions we can't price — fire-and-forget

            balance_cents = cash_cents + market_value_cents
            available_cents = cash_cents
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
                        health = self.performance_tracker.evaluate_health(name)
                        strategy_info["blended_ev_cents"] = round(health.blended_ev_cents, 2)
                        strategy_info["health_status"] = health.health_status
                        # Store for cycle-based auto-disable check
                        self._latest_health[name] = health

                    strategy_info["auto_disabled"] = name in self._auto_disabled_strategies
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
                    "dynamic_kelly_fractions": dict(self._dynamic_kelly_fractions),
                },
            )

            # Captain's Log: balance change >1%
            if self.captains_log:
                current_balance = balance_cents / 100.0
                if self._last_captains_log_balance is not None and self._last_captains_log_balance > 0:
                    pct_change = abs(current_balance - self._last_captains_log_balance) / self._last_captains_log_balance
                    if pct_change >= 0.01:
                        direction = "up" if current_balance > self._last_captains_log_balance else "down"
                        self.captains_log.record_event(NarrationEvent(
                            event_type="market_observation",
                            priority=EventPriority.ROUTINE,
                            timestamp=datetime.now(timezone.utc),
                            summary=(
                                f"Balance {direction} {pct_change:.1%}: "
                                f"${self._last_captains_log_balance:.2f} -> ${current_balance:.2f}."
                            ),
                            strategy=None,
                            metadata={},
                        ))
                        self._last_captains_log_balance = current_balance
                else:
                    self._last_captains_log_balance = current_balance

            # Push enriched positions, orders, and fills for dashboard parity
            try:
                await self.dashboard.push_positions(enriched_positions)
            except Exception as e:
                logger.debug(f"Failed to push positions: {e}")

            try:
                orders = await self.client.get_orders()
                await self.dashboard.push_orders(orders)
            except Exception as e:
                logger.debug(f"Failed to push orders: {e}")

            try:
                fills = await self.client.get_fills(limit=50)
                await self.dashboard.push_fills(fills)
            except Exception as e:
                logger.debug(f"Failed to push fills: {e}")

            try:
                settlements = await self.client.get_settlements(limit=100)
                await self.dashboard.push_settlements(settlements)

                # Bridge: close local SQLite trades that settled on exchange
                if self.journal and settlements:
                    for s in settlements:
                        ticker = s.get("ticker")
                        result = s.get("market_result")
                        if ticker and result:
                            closed = self.journal.close_trades_by_settlement(ticker, result)
                            if closed > 0:
                                logger.info(
                                    f"Settlement bridge: closed {closed} local trade(s) "
                                    f"for {ticker} (result={result})"
                                )
                                # Recompute adaptive thresholds with new data
                                self._apply_adaptive_thresholds()
            except Exception as e:
                logger.debug(f"Failed to push settlements: {e}")

            # Push IBKR holdings and balance snapshot (if IBKR is connected)
            if self._ibkr_market and self._ibkr_market._connected:
                try:
                    ibkr_positions = await self._ibkr_market.get_positions()
                    if ibkr_positions:
                        holdings = [
                            {
                                "ticker": p["ticker"],
                                "asset_class": "stock",
                                "qty": p["contracts"],
                                "avg_cost_cents": p.get("avg_cost_cents", 0),
                                "current_price_cents": p.get("current_price_cents", 0),
                                "unrealized_pnl_cents": p.get("unrealized_pnl_cents", 0),
                                "platform": "ibkr",
                            }
                            for p in ibkr_positions
                        ]
                        await self.dashboard.push_holdings(holdings)

                    ibkr_balance = await self._ibkr_market.get_balance()
                    await self.dashboard.push_balance_snapshot({
                        "platform": "ibkr",
                        "end_balance_cents": int(ibkr_balance.get("balance", 0) * 100),
                        "start_balance_cents": int(ibkr_balance.get("balance", 0) * 100),
                    })
                except Exception as e:
                    logger.debug(f"Failed to push IBKR data: {e}")

    async def _auto_disable_strategy(self, name: str, reason: str, log_prefix: str = "AUTO-DISABLE") -> None:
        """Disable a strategy, record the event, and notify Captain's Log + dashboard.

        Consolidates the repeated disable-and-notify pattern used by health checks,
        circuit breakers, and performance evaluation.
        """
        if self.strategy_manager:
            self.strategy_manager.disable_strategy(name)
        self._auto_disabled_strategies.add(name)
        self._auto_disabled_at[name] = datetime.now()

        logger.warning(f"{log_prefix}: {name} | {reason}")

        if self.captains_log:
            self.captains_log.record_event(NarrationEvent(
                event_type="strategy_change",
                priority=EventPriority.CRITICAL,
                timestamp=datetime.now(timezone.utc),
                summary=f"{log_prefix}: {name}. {reason}",
                strategy=name,
                metadata={},
            ))

        if self.dashboard:
            await self.dashboard.push_log(
                f"{log_prefix}: {name} — {reason}",
                level="WARNING",
                strategy=name,
            )
            await self.dashboard.update_strategy_disabled(
                name=name, reason=reason, disabled_by=log_prefix,
            )

    async def _check_auto_disable(self) -> None:
        """Check each strategy's health after push_state and auto-disable if critical persists.

        Tracks consecutive cycles where health_status == 'critical'. After 3
        consecutive critical cycles, disables the strategy and pushes a WARNING
        log to Supabase so the dashboard can surface the kill.
        """
        if not self.strategy_manager or not self.performance_tracker:
            return

        for name, state in self.strategy_manager._strategies.items():
            if not state.enabled:
                continue

            health = self._latest_health.get(name)
            if not health:
                continue

            if health.health_status == "critical":
                self._critical_cycle_counts[name] = self._critical_cycle_counts.get(name, 0) + 1
            else:
                self._critical_cycle_counts[name] = 0
                continue

            if self._critical_cycle_counts[name] >= 3:
                self._critical_cycle_counts[name] = 0
                await self._auto_disable_strategy(
                    name,
                    reason=(
                        f"critical health for 3 consecutive cycles "
                        f"(EV={health.blended_ev_cents:.2f}c, WR={health.blended_win_rate:.1%})"
                    ),
                )

    async def _check_auto_reenable(self) -> None:
        """Re-evaluate auto-disabled strategies after cooldown period.

        After _reenable_cooldown_hours of being disabled, re-check Bayesian
        health. If the blend has recovered (no longer critical), cautiously
        re-enable with tighter Kelly sizing. If still critical, double the
        cooldown by resetting the timestamp.
        """
        if not self.strategy_manager or not self.performance_tracker:
            return

        now = datetime.now()
        for name in list(self._auto_disabled_strategies):
            disabled_at = self._auto_disabled_at.get(name)
            if not disabled_at:
                continue

            hours_disabled = (now - disabled_at).total_seconds() / 3600
            if hours_disabled < self._reenable_cooldown_hours:
                continue

            health = self.performance_tracker.evaluate_health(name)

            if health.health_status == "critical":
                # Still bad — double the cooldown by resetting timestamp
                self._auto_disabled_at[name] = now
                logger.info(
                    f"Re-enable check: {name} still critical after {hours_disabled:.1f}h | "
                    f"EV={health.blended_ev_cents:.2f}c — extending cooldown"
                )
                continue

            # Health recovered — cautiously re-enable
            self.strategy_manager.enable_strategy(name)
            self._auto_disabled_strategies.discard(name)
            del self._auto_disabled_at[name]

            # Reset circuit breakers for a fresh start
            self._strategy_circuit_breakers[name] = {
                "consecutive_losses": 0,
                "peak_pnl_cents": 0,
                "total_pnl_cents": 0,
            }
            self._critical_cycle_counts[name] = 0

            # Apply a more conservative Kelly fraction during probation
            current_kelly = self._dynamic_kelly_fractions.get(
                name, self.config.kelly_fraction
            )
            cautious_kelly = max(0.05, current_kelly * self._reenable_tighter_factor)
            self._dynamic_kelly_fractions[name] = cautious_kelly

            # Captain's Log: strategy re-enabled
            if self.captains_log:
                self.captains_log.record_event(NarrationEvent(
                    event_type="strategy_change",
                    priority=EventPriority.SIGNIFICANT,
                    timestamp=datetime.now(timezone.utc),
                    summary=(
                        f"Re-enabled {name} after {hours_disabled:.1f}h cooldown. "
                        f"Health={health.health_status}, EV={health.blended_ev_cents:.2f}c. "
                        f"Cautious kelly={cautious_kelly:.3f}."
                    ),
                    strategy=name,
                    metadata={},
                ))

            logger.warning(
                f"AUTO-REENABLE: {name} after {hours_disabled:.1f}h cooldown | "
                f"health={health.health_status}, EV={health.blended_ev_cents:.2f}c | "
                f"kelly={cautious_kelly:.3f} (cautious)"
            )

            if self.dashboard:
                await self.dashboard.push_log(
                    f"Auto-reenabled {name} after {hours_disabled:.1f}h cooldown "
                    f"(health={health.health_status}, EV={health.blended_ev_cents:.2f}c, "
                    f"cautious kelly={cautious_kelly:.3f})",
                    level="INFO",
                    strategy=name,
                )

    async def _run_daily_review(self) -> None:
        """Generate daily review if the date has rolled over since last check.

        Calls performance_tracker.generate_daily_review() which aggregates
        per-strategy metrics, detects patterns, and compares today's raw
        stats against the all-time Bayesian blend. Results persist to the
        daily_reviews SQLite table and get pushed to dashboard logs.
        """
        if not self.performance_tracker:
            return

        today = date.today().isoformat()
        if self._last_daily_review_date == today:
            return

        # On first cycle after boot, set the date but don't generate
        # (no full day of data yet)
        if self._last_daily_review_date is None:
            self._last_daily_review_date = today
            return

        review = self.performance_tracker.generate_daily_review()
        self._last_daily_review_date = today

        if self.dashboard and review["total_trades"] > 0:
            patterns = review.get("patterns", [])
            pattern_summary = f" | patterns: {', '.join(patterns)}" if patterns else ""
            await self.dashboard.push_log(
                f"Daily review: {review['total_trades']} trades, "
                f"P&L={review['total_pnl_cents']:+d}c{pattern_summary}",
                level="INFO",
                strategy="system",
            )

    async def _run_ai_analysis(self) -> None:
        """Run Claude analysis on trade data if enough time has passed.

        Feeds PerformanceTracker data into TradeAnalyzer at a configurable
        interval (default 30 min). If Claude suggests Kelly adjustments and
        auto_apply_kelly is enabled, applies them to the per-strategy
        dynamic Kelly fractions.
        """
        if not self.trade_analyzer or not self.journal:
            return

        now = datetime.now()
        if self._last_analysis_time and (
            now - self._last_analysis_time
        ).total_seconds() < self._analysis_interval_minutes * 60:
            return

        export = self.journal.export_for_analysis()
        min_trades = self.trade_analyzer._min_trades
        if export["summary"]["total_trades"] < min_trades:
            return

        # Build config context for Claude
        config_context = {
            "strategies": get_strategy_configs() if self.use_strategy_manager else [],
            "risk": {
                "kelly_fraction": self.config.kelly_fraction,
                "max_position_size": self.config.max_position_size,
                "daily_loss_limit": self.config.daily_loss_limit,
            },
        }

        try:
            # Inject Captain's Log context for recursive learning
            log_context = None
            if self.captains_log:
                log_context = await self.captains_log.get_recent_entries_for_analysis_async(3)
            result = await self.trade_analyzer.analyze(export, config_context, log_context)
            self._last_analysis_time = now

            # Apply Kelly adjustments if available
            kelly_adj = self.trade_analyzer.get_kelly_adjustments(result)
            if kelly_adj:
                for strategy_name, suggested_kelly in kelly_adj.items():
                    old_kelly = self._dynamic_kelly_fractions.get(
                        strategy_name, self.config.kelly_fraction
                    )
                    clamped = max(0.005, min(0.05, suggested_kelly))
                    self._dynamic_kelly_fractions[strategy_name] = clamped
                    logger.info(
                        f"[AI Analysis] {strategy_name} kelly: "
                        f"{old_kelly:.3f} -> {clamped:.3f}"
                    )

            # Apply parameter flag adjustments if auto_apply_params is enabled
            if (
                self.trade_analyzer._auto_apply_params
                and self.strategy_manager
                and result.strategy_assessments
            ):
                for assessment in result.strategy_assessments:
                    if assessment.parameter_flags:
                        state = self.strategy_manager._strategies.get(
                            assessment.strategy_name
                        )
                        if state and hasattr(state.strategy, 'apply_parameter_flags'):
                            state.strategy.apply_parameter_flags(
                                assessment.parameter_flags
                            )

            # Captain's Log: AI analysis completed
            if self.captains_log:
                self.captains_log.record_event(NarrationEvent(
                    event_type="analysis",
                    priority=EventPriority.SIGNIFICANT,
                    timestamp=datetime.now(timezone.utc),
                    summary=f"AI analysis: {result.overall_summary[:200]}",
                    strategy=None,
                    metadata={"confidence": result.confidence},
                ))

            report = self.trade_analyzer.format_report(result)
            logger.info(f"AI Analysis complete:\n{report}")

            if self.dashboard:
                await self.dashboard.push_log(
                    f"AI analysis: {result.overall_summary[:200]}",
                    level="INFO",
                    strategy="analysis",
                )

        except Exception as e:
            logger.warning(f"AI analysis failed: {e}")

    def _collect_scanned_market_snapshots(self) -> List[Dict[str, Any]]:
        """Collect cached market data from strategy manager for governance feed.

        Solves the governance cold-start problem: when we have 0 open positions,
        the governor still needs market data to detect regimes.
        """
        if not self.strategy_manager:
            return []

        collected = []
        # Snapshot the dict to avoid RuntimeError if cache is modified concurrently
        for key, entry in list(self.strategy_manager._market_cache._cache.items()):
            if key.startswith("markets:") and not entry.is_expired and isinstance(entry.value, list):
                collected.extend(entry.value)
        return collected

    async def _run_governance(self) -> None:
        """Run market governance cycle: feed data, detect regime, apply decisions."""
        if not self.market_governor:
            return

        # Build market snapshots from open positions AND recently scanned markets
        snapshots = []

        # 1. Snapshots from open positions (existing behavior)
        for ticker, pos in self.open_positions.items():
            try:
                market = await self.client.get_market(ticker)
                snapshots.append(MarketSnapshot(
                    timestamp=datetime.now(),
                    ticker=ticker,
                    yes_price=float(market.get("last_price", 50)),
                    volume=int(market.get("volume", 0)),
                ))
            except Exception:
                pass

        # 2. Snapshots from scanned markets (cold-start fix)
        # When we have 0 positions, this ensures the governor still gets data
        seen_tickers = {s.ticker for s in snapshots}
        for market_data in self._last_scanned_markets:
            ticker = market_data.get("ticker", "")
            if ticker and ticker not in seen_tickers:
                try:
                    snapshots.append(MarketSnapshot(
                        timestamp=datetime.now(),
                        ticker=ticker,
                        yes_price=float(market_data.get("last_price", market_data.get("yes_price", 50))),
                        volume=int(market_data.get("volume", 0)),
                    ))
                    seen_tickers.add(ticker)
                except (ValueError, TypeError):
                    pass

        if snapshots:
            self.market_governor.feed_market_data(snapshots)

        # Gather strategy info for routing
        active_strategies = (
            list(self.strategy_manager._strategies.keys())
            if self.strategy_manager else []
        )
        safety_disabled = self._auto_disabled_strategies if self.strategy_manager else set()

        # Capture pre-cycle regime for change detection
        pre_regime = getattr(self.market_governor, '_current_regime', None)

        await self.market_governor.run_cycle(
            active_strategies=active_strategies,
            safety_disabled=safety_disabled,
            strategy_manager=self.strategy_manager,
        )

        # Captain's Log: detect regime changes and bleed alerts
        if self.captains_log:
            post_regime = getattr(self.market_governor, '_current_regime', None)
            if pre_regime and post_regime and pre_regime != post_regime:
                self.captains_log.record_event(NarrationEvent(
                    event_type="regime_shift",
                    priority=EventPriority.SIGNIFICANT,
                    timestamp=datetime.now(timezone.utc),
                    summary=f"Regime shift: {pre_regime} -> {post_regime}.",
                    strategy=None,
                    metadata={"from": str(pre_regime), "to": str(post_regime)},
                ))

            # Check for bleed alerts from governance
            bleed = getattr(self.market_governor, '_last_bleed_alert', None)
            if bleed:
                self.captains_log.record_event(NarrationEvent(
                    event_type="bleed",
                    priority=EventPriority.SIGNIFICANT,
                    timestamp=datetime.now(timezone.utc),
                    summary=f"Bleed detected: {bleed}",
                    strategy=None,
                    metadata={},
                ))
                self.market_governor._last_bleed_alert = None  # Clear after logging

    def _update_circuit_breaker_state(self, strategy_name: str, pnl_cents: int) -> None:
        """Update per-strategy circuit breaker tracking after a trade closes."""
        if strategy_name not in self._strategy_circuit_breakers:
            self._strategy_circuit_breakers[strategy_name] = {
                "consecutive_losses": 0,
                "peak_pnl_cents": 0,
                "total_pnl_cents": 0,
            }

        cb = self._strategy_circuit_breakers[strategy_name]
        cb["total_pnl_cents"] += pnl_cents

        if cb["total_pnl_cents"] > cb["peak_pnl_cents"]:
            cb["peak_pnl_cents"] = cb["total_pnl_cents"]

        if pnl_cents < 0:
            cb["consecutive_losses"] += 1
        else:
            cb["consecutive_losses"] = 0

        # Round 2 P0: persist to SQLite so breakers survive restarts
        if self.performance_tracker:
            self.performance_tracker.save_circuit_breaker(strategy_name, cb)

    async def _check_strategy_health_and_breakers(self) -> None:
        """Evaluate each strategy's health and apply hard circuit breakers.

        Runs after _apply_adaptive_thresholds() each cycle. Two layers:
        1. Performance tracker health: calls evaluate_health() and disables on "critical"
        2. Hard circuit breakers (fire regardless of health eval):
           - Win rate < 30% after 20+ trades
           - 5 consecutive losses
           - 15% drawdown from strategy's peak P&L
        """
        if not self.strategy_manager or not self.performance_tracker:
            return

        # Paper trade mode: track metrics but don't disable strategies.
        # We need unbiased data collection — circuit breakers would cut off
        # signal data before enough settlements resolve to paint the picture.
        if self.paper_trade:
            return

        for name, state in list(self.strategy_manager._strategies.items()):
            if not state.enabled:
                continue

            # --- Layer 1: Health evaluation ---
            health = self.performance_tracker.evaluate_health(name)
            self._latest_health[name] = health

            if health.health_status == "critical":
                await self._auto_disable_strategy(
                    name,
                    reason=(
                        f"critical health "
                        f"(EV={health.blended_ev_cents:.2f}c, "
                        f"WR={health.blended_win_rate:.1%}, "
                        f"confidence={health.confidence:.1%})"
                    ),
                    log_prefix="CIRCUIT BREAKER [health]",
                )
                continue

            # --- Layer 2: Hard circuit breakers ---
            cb = self._strategy_circuit_breakers.get(name, {})

            # Breaker 0 (Round 8 Cheng, tightened Round 11):
            # At 25 trades, if WR < 0.65, the strategy is not performing
            # as theorized. For a WR=0.80 thesis, P(WR ≤ 0.65 | n=25, p=0.80) ≈ 2.7%
            # — rare enough to be meaningful, more diagnostic than 0.55.
            if health.observed_trade_count >= 25 and health.blended_win_rate < 0.65:
                await self._auto_disable_strategy(
                    name,
                    reason=(
                        f"EARLY STOP: win_rate={health.blended_win_rate:.1%} < 65% "
                        f"after {health.observed_trade_count} trades — review strategy thesis"
                    ),
                    log_prefix="CIRCUIT BREAKER [early_stop]",
                )
                continue

            # Breaker 1: Win rate < 30% after 20+ trades
            if health.observed_trade_count >= 20 and health.blended_win_rate < 0.30:
                await self._auto_disable_strategy(
                    name,
                    reason=(
                        f"win_rate={health.blended_win_rate:.1%} < 30% "
                        f"over {health.observed_trade_count} trades"
                    ),
                    log_prefix="CIRCUIT BREAKER [win_rate]",
                )
                continue

            # Breaker 2: Consecutive losses (configurable, default 3)
            consecutive_losses = cb.get("consecutive_losses", 0)
            loss_limit = getattr(self.config, "consecutive_loss_limit", 3)
            if consecutive_losses >= loss_limit:
                await self._auto_disable_strategy(
                    name,
                    reason=f"{consecutive_losses} consecutive losses",
                    log_prefix="CIRCUIT BREAKER [consecutive_losses]",
                )
                continue

            # Breaker 3: 15% drawdown from peak P&L
            peak = cb.get("peak_pnl_cents", 0)
            total = cb.get("total_pnl_cents", 0)
            if peak > 0 and (peak - total) / peak >= 0.15:
                drawdown_pct = (peak - total) / peak * 100
                await self._auto_disable_strategy(
                    name,
                    reason=(
                        f"drawdown={drawdown_pct:.1f}% from peak "
                        f"(peak={peak}c, current={total}c)"
                    ),
                    log_prefix="CIRCUIT BREAKER [drawdown]",
                )

    async def _sync_positions(self) -> None:
        """Sync local position tracking with exchange.

        In paper-trade mode, load open positions from the trade journal
        instead of the exchange (paper positions don't exist on Kalshi).
        This ensures position continuity across bot restarts.
        """
        if self.paper_trade:
            # Load paper positions from journal (survives restarts)
            if not self.open_positions:
                open_trades = self.journal.get_open_trades()
                for trade in open_trades:
                    order_id = trade.get("order_id", "")
                    if not order_id.startswith("paper-"):
                        continue
                    ticker = trade.get("market_ticker")
                    if not ticker or ticker in self.open_positions:
                        continue  # Skip duplicates (keep first = oldest)
                    self.open_positions[ticker] = {
                        "trade_id": trade.get("id"),
                        "order_id": order_id,
                        "side": trade.get("side", "yes"),
                        "contracts": trade.get("contracts", 1),
                        "entry_price": trade.get("entry_price_cents", 0),
                        "strategy": trade.get("strategy", "unknown"),
                    }
                if self.open_positions:
                    logger.info(
                        f"[PAPER] Loaded {len(self.open_positions)} positions from journal: "
                        f"{list(self.open_positions.keys())}"
                    )
            return
        positions = await self.client.get_positions()

        # Update local tracking with full Kalshi fields
        exchange_tickers = set()
        for pos in positions:
            ticker = pos.get("market_ticker") or pos.get("ticker")
            if ticker and pos.get("position", 0) != 0:
                exchange_tickers.add(ticker)

                side = "yes" if pos["position"] > 0 else "no"
                contracts = abs(pos["position"])

                if ticker not in self.open_positions:
                    self.open_positions[ticker] = {
                        "contracts": contracts,
                        "side": side,
                        "synced_from_exchange": True,
                    }

                # Always update enriched fields from exchange
                self.open_positions[ticker].update({
                    "contracts": contracts,
                    "side": side,
                    "total_traded": pos.get("total_traded", 0),
                    "market_exposure": pos.get("market_exposure", 0),
                    "realized_pnl": pos.get("realized_pnl", 0),
                    "fees_paid": pos.get("fees_paid", 0),
                    "resting_orders_count": pos.get("resting_orders_count", 0),
                    "last_updated_ts": pos.get("last_updated_ts"),
                })

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
                    # Paper trades: resolve settlement via market result
                    if self.paper_trade and market.get("result"):
                        result = market["result"]
                        closed = self.journal.close_trades_by_settlement(ticker, result)

                        # Calculate settlement P&L for risk management feedback
                        side = position.get("side", "yes")
                        entry = position.get("entry_price", 0)
                        contracts = position.get("contracts", 1)
                        if result == "yes":
                            settle_price = 100 if side == "yes" else 0
                        else:
                            settle_price = 0 if side == "yes" else 100
                        pnl = (settle_price - entry) * contracts

                        logger.info(
                            f"[PAPER] Settlement: {ticker} -> {result} | "
                            f"side={side} entry={entry}c settle={settle_price}c "
                            f"P&L={pnl:+d}c | closed {closed} journal entries"
                        )

                        if closed > 0:
                            # Feed P&L to risk management (resets consecutive loss counter on wins)
                            strategy_name = position.get("strategy", "calibration_edge")
                            self._update_circuit_breaker_state(strategy_name, pnl)
                            self.risk.record_trade_result(ticker, pnl, contracts)
                            if self.market_governor:
                                self.market_governor.record_trade_outcome(strategy_name, pnl)
                            self._apply_adaptive_thresholds()
                            self._check_lab_milestones()
                    else:
                        logger.info(f"Market {ticker} no longer open, removing from tracking")
                    del self.open_positions[ticker]
                    if self.strategy_manager:
                        self.strategy_manager.record_position_close(ticker)
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

            if self.paper_trade:
                # Paper trade: simulate instant sell, no API call
                order = {"order_id": f"paper-exit-{str(uuid.uuid4())[:8]}"}
                logger.info(
                    f"[PAPER] Simulated exit: {ticker} | sell {contracts} @ "
                    f"{exit_signal.current_price_cents}c | reason: {exit_signal.exit_type}"
                )
            else:
                # Round 9 P0 (Tanaka): Closing orders bypass the API circuit breaker.
                # Position-closing is more critical than circuit breaker protection —
                # holding through a flash crash is worse than a failed sell attempt.
                order = await self.client.create_limit_order(
                    ticker=ticker,
                    side=side,
                    action="sell",
                    count=contracts,
                    price_cents=exit_signal.current_price_cents,
                    bypass_circuit_breaker=True,
                )

            # Update journal
            if trade_id := position.get("trade_id"):
                pnl = self.journal.close_trade(
                    trade_id=trade_id,
                    exit_price_cents=exit_signal.current_price_cents,
                    exit_order_id=order.get("order_id"),
                    exit_reason=exit_signal.exit_type,
                )

                # Record in risk management (skip for paper trades —
                # paper P&L must not contaminate daily_pnl / dashboard balance)
                if not self.paper_trade:
                    self.risk.record_trade_result(
                        ticker=ticker,
                        profit_loss_cents=pnl,
                        position_size_dollars=contracts,
                    )

                # Update circuit breaker state for this strategy
                self._update_circuit_breaker_state(
                    position.get("strategy", "mean_reversion"), pnl
                )

                # Record outcome for governance fitness attribution
                if self.market_governor:
                    self.market_governor.record_trade_outcome(
                        position.get("strategy", "mean_reversion"), pnl
                    )

                # Sync close to Supabase dashboard (skip for paper trades)
                if self.dashboard and position.get("order_id") and not self.paper_trade:
                    await self.dashboard.push_trade_close(
                        order_id=position["order_id"],
                        exit_price_cents=exit_signal.current_price_cents,
                        pnl_cents=pnl,
                        exit_reason=exit_signal.exit_type,
                    )

            # Captain's Log: trade closed
            if self.captains_log and trade_id:
                mode_tag = "[PAPER] " if self.paper_trade else ""
                self.captains_log.record_event(NarrationEvent(
                    event_type="trade",
                    priority=EventPriority.SIGNIFICANT,
                    timestamp=datetime.now(timezone.utc),
                    summary=(
                        f"{mode_tag}Closed {ticker} ({exit_signal.exit_type}). "
                        f"P&L: {pnl:+d}c (${pnl / 100:+.2f})."
                    ),
                    strategy=position.get("strategy", "mean_reversion"),
                    metadata={"ticker": ticker, "pnl_cents": pnl, "exit_type": exit_signal.exit_type, "paper_trade": self.paper_trade},
                ))

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
                    await self._auto_disable_strategy(
                        strategy_name,
                        reason=(
                            f"sustained negative EV ({health.blended_ev_cents:.2f}c) "
                            f"over {health.consecutive_warnings} evaluations"
                        ),
                    )
                elif health.health_status != "healthy":
                    logger.warning(
                        f"Strategy {strategy_name}: {health.health_status} | "
                        f"blended EV={health.blended_ev_cents:.2f}c, "
                        f"confidence={health.confidence:.1%}"
                    )

            # Recompute adaptive thresholds after each trade close
            self._apply_adaptive_thresholds()

            # Check research lab milestone triggers
            self._check_lab_milestones()

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

        # Cache scanned market data for governance feed (cold-start fix)
        # Pull from strategy manager's market cache to feed the governor
        self._last_scanned_markets = self._collect_scanned_market_snapshots()

        # Record cycle for health monitor
        if self.health_monitor:
            self.health_monitor.record_cycle(found_opportunities=bool(opportunities))

        # Round 7 P0 (Sullivan) + Round 8 P0 (Vasquez): Escalating inaction alerting.
        # Track which enabled strategies found zero opportunities. Tiered severity:
        # WARNING at ~25 min, ERROR at ~1h, CRITICAL at ~2h. Re-alerts every ~50 min.
        if self.strategy_manager:
            opp_by_strategy = {}
            for opp in opportunities:
                opp_by_strategy[opp.strategy_name] = opp_by_strategy.get(opp.strategy_name, 0) + 1
            for name, state in self.strategy_manager._strategies.items():
                if not state.enabled:
                    continue
                if opp_by_strategy.get(name, 0) > 0:
                    self._inaction_cycles[name] = 0
                    self._inaction_last_alert_cycle[name] = 0
                else:
                    self._inaction_cycles[name] = self._inaction_cycles.get(name, 0) + 1
                    cycles = self._inaction_cycles[name]
                    last_alert = self._inaction_last_alert_cycle.get(name, 0)
                    should_alert = (
                        cycles >= self._inaction_alert_threshold
                        and (last_alert == 0 or cycles - last_alert >= self._inaction_repeat_interval)
                    )
                    if should_alert:
                        self._inaction_last_alert_cycle[name] = cycles
                        interval = self.config.poll_interval_seconds
                        minutes = (cycles * interval) / 60
                        # Escalating severity
                        if cycles >= self._inaction_critical_threshold:
                            logger.critical(
                                f"INACTION CRITICAL: Strategy '{name}' — ZERO "
                                f"opportunities for {cycles} cycles (~{minutes:.0f} min). "
                                f"Strategy may be broken or markets unavailable."
                            )
                        elif cycles >= self._inaction_error_threshold:
                            logger.error(
                                f"INACTION ERROR: Strategy '{name}' — ZERO "
                                f"opportunities for {cycles} cycles (~{minutes:.0f} min). "
                                f"Investigate: runtime state, market availability, thresholds."
                            )
                        else:
                            logger.warning(
                                f"INACTION WARNING: Strategy '{name}' — ZERO "
                                f"opportunities for {cycles} cycles (~{minutes:.0f} min). "
                                f"Is it misconfigured or are markets outside its range?"
                            )

        if not opportunities:
            self._consecutive_empty_scans += 1
            self._self_regulate()
            logger.info("Scan complete — no opportunities across all strategies")
            return

        # Reset empty scan counter on success
        self._consecutive_empty_scans = 0
        self._self_regulate()

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

        # Calculate position size using learned stats (Bayesian blend) if available
        if self.performance_tracker:
            stats = self.performance_tracker.get_blended_stats("mean_reversion")
        else:
            stats = self.strategy.get_historical_stats()
        kelly_override = self._dynamic_kelly_fractions.get("mean_reversion")
        size_result = self.risk.calculate_position_size(
            win_rate=stats["win_rate"],
            avg_win_cents=stats["avg_win_cents"],
            avg_loss_cents=stats["avg_loss_cents"],
            ticker=ticker,
            kelly_override=kelly_override,
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

        # Round 2 P0: Pre-trade EV gate — reject trades with negative net EV
        # Paper trade mode: skip EV gate — we need unbiased signal data
        edge = state.strategy.calculate_edge(commission_cents=2.0)
        if edge["expected_value_net_cents"] <= 0 and not self.paper_trade:
            logger.info(
                f"Trade BLOCKED {ticker} [{strategy_name}]: negative net EV "
                f"({edge['expected_value_net_cents']:+.2f}c/trade, "
                f"breakeven WR={edge['breakeven_win_rate']:.0%}, "
                f"current WR={edge['assumed_win_rate']:.0%})"
            )
            return False

        # Use learned Bayesian blend for sizing (falls back to strategy priors)
        # Round 9 P0 (Nakamura): Early-stage Bayesian protection.
        # With k=5 prior strength, a single settlement loss (-80c) can flip
        # the blended stats so negative that Kelly produces 0 contracts,
        # permanently killing the strategy after one bad trade.
        # Fix: Use pure prior stats until we have ≥3 observed trades.
        # At n=3, the blend is 5/(5+3)=62.5% prior, which dampens outliers.
        if self.performance_tracker:
            health = self.performance_tracker.evaluate_health(strategy_name)
            if health and health.observed_trade_count >= 3:
                stats = self.performance_tracker.get_blended_stats(strategy_name)
                logger.debug(
                    f"Sizing {ticker} [{strategy_name}]: using BLENDED stats "
                    f"(n={health.observed_trade_count}, confidence={health.confidence:.1%})"
                )
            else:
                stats = state.strategy.get_historical_stats()
                n = health.observed_trade_count if health else 0
                logger.info(
                    f"Sizing {ticker} [{strategy_name}]: using PURE PRIOR stats "
                    f"(only {n} trades — need ≥3 for Bayesian blend)"
                )
        else:
            stats = state.strategy.get_historical_stats()
        kelly_override = self._dynamic_kelly_fractions.get(strategy_name)
        size_result = self.risk.calculate_position_size(
            win_rate=stats["win_rate"],
            avg_win_cents=stats["avg_win_cents"],
            avg_loss_cents=stats["avg_loss_cents"],
            ticker=ticker,
            kelly_override=kelly_override,
        )

        contracts = size_result["contracts"]
        if contracts < 1:
            logger.debug(f"Position size too small for {ticker}: {contracts}")
            return False

        return await self._place_trade(ticker, opp, contracts, strategy_name)

    async def _wait_for_fill(
        self,
        order_id: str,
        ticker: str,
        ttl_seconds: int = 90,
    ) -> int:
        """
        Round 10 P0 (Desai): Poll order status until filled or TTL expires.

        Without fill confirmation, the bot records phantom positions from
        unfilled limit orders. These ghost positions block re-entry on the
        market and corrupt risk calculations. This method ensures we only
        record positions that are actually held.

        Args:
            order_id: The Kalshi order ID to monitor
            ticker: Market ticker (for logging)
            ttl_seconds: Maximum time to wait for fill (default 90s)

        Returns:
            Number of filled contracts (0 if unfilled/expired/cancelled)
        """
        poll_interval = 5  # seconds between status checks
        elapsed = 0

        while elapsed < ttl_seconds:
            try:
                order_info = await self.client.get_order(order_id)
                status = order_info.get("status", "")
                total_count = order_info.get("count", 0)
                remaining = order_info.get("remaining_count", 0)
                filled = total_count - remaining if total_count else 0

                if status == "executed" or remaining == 0:
                    logger.info(
                        f"Order FILLED for {ticker}: {filled} contracts "
                        f"(order_id={order_id}, waited {elapsed}s)"
                    )
                    return filled

                if status in ("canceled", "expired"):
                    logger.info(
                        f"Order {status.upper()} for {ticker} "
                        f"(order_id={order_id}, filled={filled})"
                    )
                    return filled  # Return partial fill count (may be 0)

                logger.debug(
                    f"Order PENDING for {ticker}: {remaining}/{total_count} remaining "
                    f"(order_id={order_id}, elapsed={elapsed}s/{ttl_seconds}s)"
                )

            except Exception as e:
                logger.warning(f"Error polling order status for {order_id}: {e}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # TTL expired — check one final time
        try:
            order_info = await self.client.get_order(order_id)
            total_count = order_info.get("count", 0)
            remaining = order_info.get("remaining_count", 0)
            return total_count - remaining if total_count else 0
        except Exception:
            return 0

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

            # Paper trade mode: simulate instant fill, write real journal entries
            if self.paper_trade:
                order_id = f"paper-{str(uuid.uuid4())[:8]}"
                actual_contracts = contracts

                trade_id = self.journal.log_trade(
                    market_ticker=ticker,
                    side=opp.side,
                    action="buy",
                    contracts=actual_contracts,
                    price_cents=opp.entry_price_cents,
                    order_id=order_id,
                    reasoning=opp.reasoning,
                    strategy=strategy_name,
                    metadata={"paper_trade": True, "simulated_fill": True},
                    is_paper=True,
                )

                logger.info(
                    f"[PAPER] Simulated fill: {ticker} | {opp.side} {actual_contracts} @ "
                    f"{opp.entry_price_cents}c | Strategy: {strategy_name} | "
                    f"Score: {opp.score:.1f} | {opp.reasoning}"
                )

                # Fall through to position tracking below (same as live)
            else:
                # --- LIVE trading path ---
                # Check exchange status before placing order
                exchange_status = await self.client.check_exchange_status()
                if not exchange_status["trading_active"]:
                    logger.info(
                        f"Skipping trade {ticker}: exchange not open "
                        f"(status={exchange_status['exchange_status']})"
                    )
                    return False

                # Place limit order
                order = await self.client.create_limit_order(
                    ticker=ticker,
                    side=opp.side,
                    action="buy",
                    count=contracts,
                    price_cents=opp.entry_price_cents,
                )

                order_id = order.get("order_id")
                if not order_id:
                    logger.error(f"No order_id returned for {ticker} — cannot confirm fill")
                    return False

                # Round 10 P0 (Desai): Fill confirmation loop.
                # Don't record position until order is confirmed filled.
                # Without this, unfilled limit orders become phantom positions
                # that block re-entry and corrupt risk calculations.
                fill_ttl = getattr(self.config, 'order_fill_ttl_seconds', 90)
                filled_contracts = await self._wait_for_fill(
                    order_id, ticker, ttl_seconds=fill_ttl
                )

                if filled_contracts == 0:
                    # TTL expired with no fill — cancel and move on
                    cancelled = await self.client.cancel_order(order_id)
                    logger.info(
                        f"Order UNFILLED for {ticker} after {fill_ttl}s — "
                        f"{'cancelled' if cancelled else 'cancel failed'} "
                        f"(order_id={order_id})"
                    )
                    return False

                # Use actual filled count (may differ from requested on partial fills)
                actual_contracts = filled_contracts

                # Log trade (confirmed fill)
                trade_id = self.journal.log_trade(
                    market_ticker=ticker,
                    side=opp.side,
                    action="buy",
                    contracts=actual_contracts,
                    price_cents=opp.entry_price_cents,
                    order_id=order_id,
                    reasoning=opp.reasoning,
                    strategy=strategy_name,
                )

            # Track position (confirmed fill only)
            self.open_positions[ticker] = {
                "trade_id": trade_id,
                "order_id": order_id,
                "side": opp.side,
                "contracts": actual_contracts,
                "entry_price": opp.entry_price_cents,
                "strategy": strategy_name,
            }

            # Record position open in risk management
            self.risk.record_position_open(ticker, float(actual_contracts))

            # Notify strategy manager
            if self.strategy_manager:
                self.strategy_manager.record_position_open(ticker, strategy_name)

            # Push trade to Supabase dashboard (skip for paper trades)
            if self.dashboard and not self.paper_trade:
                await self.dashboard.push_trade(
                    market_ticker=ticker,
                    side=opp.side,
                    action="buy",
                    contracts=actual_contracts,
                    entry_price_cents=opp.entry_price_cents,
                    strategy=strategy_name,
                    order_id=order_id,
                    reasoning=opp.reasoning,
                )

            # Captain's Log: trade opened
            if self.captains_log:
                mode_tag = "[PAPER] " if self.paper_trade else ""
                self.captains_log.record_event(NarrationEvent(
                    event_type="trade",
                    priority=EventPriority.SIGNIFICANT,
                    timestamp=datetime.now(timezone.utc),
                    summary=(
                        f"{mode_tag}Opened {opp.side.upper()} {actual_contracts} @ {opp.entry_price_cents}c on {ticker}. "
                        f"Score: {opp.score:.1f}. {opp.reasoning[:100]}"
                    ),
                    strategy=strategy_name,
                    metadata={"ticker": ticker, "side": opp.side, "price": opp.entry_price_cents, "paper_trade": self.paper_trade},
                ))

            # Record trade for health monitor (resets zero-opp counter, reverts threshold widening)
            if self.health_monitor:
                self.health_monitor.record_trade()

            fill_note = "" if actual_contracts == contracts else f" (requested {contracts}, filled {actual_contracts})"
            logger.info(
                f"Trade CONFIRMED: {ticker} | {opp.side} {actual_contracts} @ {opp.entry_price_cents}c | "
                f"Strategy: {strategy_name} | Score: {opp.score:.1f}{fill_note} | {opp.reasoning}"
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

        # If config.yaml defines a strategies list, run in multi-strategy mode by default.
        # Legacy mode still exists (run_bot.py without --multi), but the module entrypoint
        # should follow the repo's primary configuration.
        strategy_configs = None
        try:
            strategy_configs = get_strategy_configs()
        except Exception as e:
            logger.warning(f"Could not load strategy configs — starting in legacy mode: {e}")

        use_multi = bool(strategy_configs)
        bot = KalshiTradingBot(
            config,
            use_strategy_manager=use_multi,
            strategy_configs=strategy_configs if use_multi else None,
        )
        await bot.start()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
