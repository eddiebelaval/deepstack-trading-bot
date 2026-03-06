"""
Health Monitor — Self-Healing Watchdog for DeepStack

Periodic diagnostic loop that detects "zombie state" (bot alive but
finding zero opportunities) and other degradation. Runs alongside the
trading and command loops as a third concurrent async task.

Three tiers:
  - Quick heartbeat (60s): cycle timing + API ping
  - Full diagnostic (5 min): all health checks
  - Self-clean (30 min): log rotation, WAL checkpoint, stale data purge

Self-healing actions are CLAMPED (max 30% from original values) and
REVERSIBLE. Safety rails (circuit breakers, daily limits) are never
touched.
"""

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .dashboard_sync import DashboardSync
    from .captains_log import CaptainsLog

logger = logging.getLogger(__name__)

# Intervals (seconds)
QUICK_HEARTBEAT_INTERVAL = 60
FULL_DIAGNOSTIC_INTERVAL = 300  # 5 minutes
SELF_CLEAN_INTERVAL = 1800  # 30 minutes

# Thresholds
ZERO_OPP_WARN_CYCLES = 10
ZERO_OPP_HEAL_CYCLES = 30
MAX_THRESHOLD_WIDEN_PCT = 0.30  # Max 30% widening from original
WAL_CHECKPOINT_BYTES = 50 * 1024 * 1024  # 50MB
LOG_ROTATE_BYTES = 100 * 1024 * 1024  # 100MB
STALE_REGIME_ROWS_MAX = 1000
STALE_REGIME_ROWS_KEEP = 500
STALE_CAPTAINS_LOG_MAX = 100
STALE_CAPTAINS_LOG_KEEP = 50
CYCLE_STALL_SECONDS = 300  # 5 minutes without a cycle = stalled
ZERO_MARKETS_WARN_CYCLES = 10   # WARNING after 10 cycles (~10 min) of zero markets
ZERO_MARKETS_CRITICAL_CYCLES = 60  # CRITICAL after 60 cycles (~1 hour) — Telegram alert


@dataclass
class HealthStatus:
    """Point-in-time health assessment."""

    timestamp: datetime
    overall_status: str  # "healthy", "degraded", "critical"
    uptime_seconds: float
    last_trade_time: Optional[str]
    cycles_since_last_trade: int
    cycles_with_zero_opportunities: int
    api_status: str  # "connected", "disconnected", "error"
    api_latency_ms: float
    market_data_status: str  # "fresh", "stale", "unavailable"
    markets_available: Dict[str, int]
    strategy_health: Dict[str, Dict[str, Any]]
    db_wal_size_mb: float
    log_size_mb: float
    governor_regime: str
    governor_confidence: float
    errors_last_hour: List[str]
    self_heal_actions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for Supabase push."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status,
            "uptime_seconds": int(self.uptime_seconds),
            "last_trade_time": self.last_trade_time,
            "cycles_since_last_trade": self.cycles_since_last_trade,
            "cycles_with_zero_opportunities": self.cycles_with_zero_opportunities,
            "api_status": self.api_status,
            "api_latency_ms": round(self.api_latency_ms, 1),
            "market_data_status": self.market_data_status,
            "markets_available": self.markets_available,
            "strategy_health": self.strategy_health,
            "db_wal_size_mb": round(self.db_wal_size_mb, 2),
            "log_size_mb": round(self.log_size_mb, 2),
            "governor_regime": self.governor_regime,
            "governor_confidence": round(self.governor_confidence, 3),
            "errors_last_hour": self.errors_last_hour[-20:],
            "self_heal_actions": self.self_heal_actions[-10:],
        }


class HealthMonitor:
    """
    Self-healing health watchdog for the trading bot.

    Runs as a periodic async task. Detects degradation, self-cleans,
    self-heals within clamped bounds, and pushes status to Supabase.
    """

    def __init__(
        self,
        bot: Any,  # KalshiTradingBot (avoid circular import)
        db_path: Optional[Path] = None,
        log_path: Optional[Path] = None,
    ):
        self._bot = bot
        self._db_path = db_path or Path(getattr(bot.config, "journal_db_path", "trades.db"))
        self._log_path = log_path

        # Timing
        self._start_time = time.time()
        self._last_full_diagnostic = 0.0
        self._last_self_clean = 0.0
        self._last_cycle_time: Optional[float] = None

        # Counters
        self._zero_opp_counter = 0
        self._zero_markets_counter = 0  # Consecutive cycles with zero markets from API
        self._total_cycles = 0
        self._cycles_since_last_trade = 0
        self._error_buffer: List[str] = []  # Rolling buffer of recent errors
        self._heal_actions: List[str] = []  # Actions taken this session
        self._zero_markets_alerted = False  # Prevent Telegram spam

        # Original threshold values (for clamped widening)
        self._original_thresholds: Dict[str, Dict[str, Any]] = {}
        self._threshold_widen_active = False

        # API health tracking
        self._api_consecutive_failures = 0
        self._supabase_consecutive_failures = 0

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    def record_cycle(self, found_opportunities: bool) -> None:
        """Called by the trading loop after each scan cycle."""
        self._total_cycles += 1
        self._last_cycle_time = time.time()

        if found_opportunities:
            self._zero_opp_counter = 0
        else:
            self._zero_opp_counter += 1

    def record_trade(self) -> None:
        """Called when a trade is executed."""
        self._cycles_since_last_trade = 0
        # Reset adaptive threshold adjustments after first trade
        if self._threshold_widen_active:
            self._revert_threshold_widening()

    def record_error(self, error_msg: str) -> None:
        """Record an error for the health report."""
        timestamp = datetime.now(timezone.utc).isoformat()
        self._error_buffer.append(f"[{timestamp}] {error_msg[:200]}")
        self._error_buffer = self._error_buffer[-100:]

    async def run_loop(self, shutdown_event: asyncio.Event) -> None:
        """Main health monitor loop. Runs until shutdown."""
        logger.info("Health monitor started")

        while not shutdown_event.is_set():
            try:
                now = time.time()

                # Quick heartbeat every 60s
                self._check_cycle_timing()

                # Full diagnostic every 5 min
                if now - self._last_full_diagnostic >= FULL_DIAGNOSTIC_INTERVAL:
                    await self._run_full_diagnostic()
                    self._last_full_diagnostic = now

                # Self-clean every 30 min
                if now - self._last_self_clean >= SELF_CLEAN_INTERVAL:
                    await self._run_self_clean()
                    self._last_self_clean = now

            except Exception as e:
                logger.error(f"Health monitor error: {e}", exc_info=True)

            # Wait for next heartbeat or shutdown
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=QUICK_HEARTBEAT_INTERVAL,
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Normal — continue loop

        logger.info("Health monitor stopped")

    # ── Full Diagnostic ─────────────────────────────────────────────

    async def _run_full_diagnostic(self) -> None:
        """Run all health checks and push status."""
        status = HealthStatus(
            timestamp=datetime.now(timezone.utc),
            overall_status="healthy",
            uptime_seconds=self.uptime_seconds,
            last_trade_time=None,
            cycles_since_last_trade=self._cycles_since_last_trade,
            cycles_with_zero_opportunities=self._zero_opp_counter,
            api_status="unknown",
            api_latency_ms=0.0,
            market_data_status="unknown",
            markets_available={},
            strategy_health={},
            db_wal_size_mb=0.0,
            log_size_mb=0.0,
            governor_regime="unknown",
            governor_confidence=0.0,
            errors_last_hour=self._recent_errors(),
            self_heal_actions=list(self._heal_actions),
        )

        # Run checks
        await self._check_api_health(status)
        self._check_market_data(status)
        self._check_strategy_activity(status)
        self._check_db_health(status)
        self._check_log_growth(status)
        self._check_governor(status)

        # Determine overall status
        status.overall_status = self._compute_overall_status(status)

        # Self-heal if degraded
        await self._self_heal(status)

        # Push to Supabase
        await self._push_health_status(status)

        # Alert if degraded
        await self._alert_if_degraded(status)

        logger.info(
            "Health check | status=%s opp_drought=%d api=%s governor=%s(%.2f) "
            "wal=%.1fMB log=%.1fMB",
            status.overall_status,
            status.cycles_with_zero_opportunities,
            status.api_status,
            status.governor_regime,
            status.governor_confidence,
            status.db_wal_size_mb,
            status.log_size_mb,
        )

    # ── Individual Checks ───────────────────────────────────────────

    async def _check_api_health(self, status: HealthStatus) -> None:
        """Check Kalshi API connectivity and latency."""
        if not self._bot.client:
            status.api_status = "disconnected"
            return

        try:
            start = time.time()
            balance = await self._bot.client.get_balance()
            latency = (time.time() - start) * 1000
            status.api_status = "connected"
            status.api_latency_ms = latency
            self._api_consecutive_failures = 0
        except Exception as e:
            self._api_consecutive_failures += 1
            status.api_status = f"error ({self._api_consecutive_failures} consecutive)"
            self.record_error(f"API health check failed: {e}")

    def _check_market_data(self, status: HealthStatus) -> None:
        """Check if we're getting non-zero markets from scans."""
        scanned = self._bot._last_scanned_markets
        if not scanned:
            self._zero_markets_counter += 1
            status.market_data_status = "unavailable"

            if self._zero_markets_counter >= ZERO_MARKETS_CRITICAL_CYCLES:
                status.market_data_status = "critical"
                logger.error(
                    "CRITICAL: %d consecutive cycles with zero markets. "
                    "API may be down, series tickers invalid, or account restricted.",
                    self._zero_markets_counter,
                )
                if not self._zero_markets_alerted:
                    self._send_zero_markets_alert()
                    self._zero_markets_alerted = True
            elif self._zero_markets_counter >= ZERO_MARKETS_WARN_CYCLES:
                status.market_data_status = "degraded"
                logger.warning(
                    "Zero markets for %d consecutive cycles. "
                    "Check series tickers and API connectivity.",
                    self._zero_markets_counter,
                )
            return

        # Markets found — reset counter
        self._zero_markets_counter = 0
        self._zero_markets_alerted = False

        # Count markets per series
        series_counts: Dict[str, int] = {}
        for market in scanned:
            series = market.get("series_ticker", market.get("ticker", "unknown"))[:4]
            series_counts[series] = series_counts.get(series, 0) + 1

        status.markets_available = series_counts
        status.market_data_status = "fresh"

    def _send_zero_markets_alert(self) -> None:
        """Send Telegram alert when market data has been empty for too long."""
        telegram = getattr(self._bot, "telegram_bridge", None)
        if not telegram or not telegram.is_available:
            return

        message = (
            "[HEALTH ALERT] Market data feed dead.\n"
            f"{self._zero_markets_counter} consecutive cycles with zero markets.\n"
            "Possible causes: series tickers invalid, API down, account restricted.\n"
            "Manual intervention required."
        )

        async def _send():
            try:
                await telegram._send_message(message)
            except Exception:
                pass

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_send())
        except RuntimeError:
            pass

    def _check_strategy_activity(self, status: HealthStatus) -> None:
        """Check if strategies are finding any candidates."""
        if not self._bot.strategy_manager:
            return

        for name, state in self._bot.strategy_manager._strategies.items():
            health_info: Dict[str, Any] = {
                "enabled": state.enabled,
                "scan_count": state.scan_count,
                "trade_count": state.trade_count,
            }

            # Check performance tracker health if available
            if self._bot.performance_tracker:
                try:
                    health = self._bot.performance_tracker.evaluate_health(name)
                    health_info["health_status"] = health.health_status
                    health_info["blended_ev_cents"] = round(health.blended_ev_cents, 2)
                    health_info["blended_win_rate"] = round(health.blended_win_rate, 3)
                except Exception:
                    health_info["health_status"] = "unknown"

            # Check latest health from bot
            if name in self._bot._latest_health:
                h = self._bot._latest_health[name]
                health_info["observed_trades"] = getattr(h, "observed_trade_count", 0)

            status.strategy_health[name] = health_info

    def _check_cycle_timing(self) -> None:
        """Check if the trading loop is cycling on time."""
        if self._last_cycle_time is None:
            return

        elapsed = time.time() - self._last_cycle_time
        if elapsed > CYCLE_STALL_SECONDS:
            self.record_error(
                f"Trading loop stalled: {elapsed:.0f}s since last cycle "
                f"(threshold: {CYCLE_STALL_SECONDS}s)"
            )
            logger.warning(
                "Trading loop may be stalled: %.0fs since last cycle", elapsed
            )

    def _check_db_health(self, status: HealthStatus) -> None:
        """Check SQLite database health."""
        db_path = self._db_path
        wal_path = Path(f"{db_path}-wal")

        if wal_path.exists():
            wal_size = wal_path.stat().st_size
            status.db_wal_size_mb = wal_size / (1024 * 1024)
        else:
            status.db_wal_size_mb = 0.0

    def _check_log_growth(self, status: HealthStatus) -> None:
        """Check stderr log size."""
        if self._log_path and self._log_path.exists():
            status.log_size_mb = self._log_path.stat().st_size / (1024 * 1024)
        else:
            status.log_size_mb = 0.0

    def _check_governor(self, status: HealthStatus) -> None:
        """Check market governor state."""
        gov = self._bot.market_governor
        if not gov:
            status.governor_regime = "disabled"
            status.governor_confidence = 0.0
            return

        current = getattr(gov, "current_regime", None)
        if current:
            status.governor_regime = current.regime.value
            status.governor_confidence = current.confidence
        else:
            status.governor_regime = "no_data"
            status.governor_confidence = 0.0

    # ── Self-Healing ────────────────────────────────────────────────

    async def _self_heal(self, status: HealthStatus) -> None:
        """Apply self-healing actions based on detected issues."""

        # 1. Zero opportunities for exactly WARN threshold: log once
        if self._zero_opp_counter == ZERO_OPP_WARN_CYCLES:
            logger.warning(
                "Zero opportunities for %d consecutive cycles — "
                "consider reviewing thresholds",
                self._zero_opp_counter,
            )
            self._heal_actions.append(
                f"warn: {self._zero_opp_counter} cycles with zero opportunities"
            )

        # 2. Zero opportunities for 30+ cycles: auto-widen min_score
        #    Only widen if the bot is actually seeing markets (>10 scanned);
        #    widening thresholds when API returns 0 markets is pointless.
        has_markets = len(self._bot._last_scanned_markets) > 10
        if (
            self._zero_opp_counter >= ZERO_OPP_HEAL_CYCLES
            and not self._threshold_widen_active
            and has_markets
        ):
            self._apply_threshold_widening()

        # 3. Governor stuck at zero confidence — force-feed with scanned market data
        governor_stuck = (
            status.governor_confidence <= 0.1
            and status.governor_regime in ("low_vol_calm", "no_data")
            and self._total_cycles > 10
        )
        scanned = self._bot._last_scanned_markets
        if governor_stuck and scanned and self._bot.market_governor:
            from .market_governor import MarketSnapshot

            snapshots = self._build_market_snapshots(scanned[:50])
            if snapshots:
                self._bot.market_governor.feed_market_data(snapshots)
                self._heal_actions.append("force_fed_governor_with_scanned_data")
                logger.info(
                    "Self-heal: force-fed governor with %d scanned market snapshots",
                    len(snapshots),
                )

        # 4. Claude analysis failing — reduce context
        # (Handled by the truncation fix in trade_analyzer.py)

        # 5. Supabase connection lost
        if self._supabase_consecutive_failures >= 3:
            dashboard = self._bot.dashboard
            if dashboard:
                try:
                    await dashboard.connect()
                    self._supabase_consecutive_failures = 0
                    self._heal_actions.append("reconnected_supabase")
                    logger.info("Self-heal: reconnected Supabase")
                except Exception:
                    pass

    def _build_market_snapshots(self, markets: List[Dict[str, Any]]) -> list:
        """Build MarketSnapshot list from raw market dicts, skipping invalid entries."""
        from .market_governor import MarketSnapshot

        snapshots = []
        now = datetime.now()
        for m in markets:
            try:
                snapshots.append(MarketSnapshot(
                    timestamp=now,
                    ticker=m.get("ticker", ""),
                    yes_price=float(m.get("last_price", m.get("yes_price", 50))),
                    volume=int(m.get("volume", 0)),
                ))
            except (ValueError, TypeError):
                continue
        return snapshots

    def _apply_threshold_widening(self) -> None:
        """Auto-widen min_score thresholds by 20% (clamped at 30% from original)."""
        if not self._bot.strategy_manager:
            return

        self._threshold_widen_active = True
        widened_count = 0

        for name, state in self._bot.strategy_manager._strategies.items():
            if not state.enabled:
                continue

            strategy = state.strategy

            # Capture originals on first widening
            if name not in self._original_thresholds:
                self._original_thresholds[name] = {}
                for param in ("min_score", "min_volume"):
                    if hasattr(strategy, param):
                        self._original_thresholds[name][param] = getattr(strategy, param)

            # Widen each threshold by 20% (lower the bar), clamped at 30% from original
            originals = self._original_thresholds.get(name, {})
            for param in ("min_score", "min_volume"):
                if not hasattr(strategy, param) or param not in originals:
                    continue
                current = getattr(strategy, param)
                floor = originals[param] * (1 - MAX_THRESHOLD_WIDEN_PCT)
                widened = max(floor, current * 0.80)
                if widened != current:
                    setattr(strategy, param, int(widened))
                    widened_count += 1

        if widened_count > 0:
            self._heal_actions.append(
                f"auto_widened_thresholds_20pct ({widened_count} params)"
            )
            logger.warning(
                "Self-heal: auto-widened %d threshold params by 20%% "
                "after %d zero-opportunity cycles (reversible, clamped at 30%%)",
                widened_count,
                self._zero_opp_counter,
            )

    def _revert_threshold_widening(self) -> None:
        """Revert auto-widened thresholds back to original values."""
        if not self._bot.strategy_manager or not self._original_thresholds:
            return

        reverted = 0
        for name, originals in self._original_thresholds.items():
            state = self._bot.strategy_manager._strategies.get(name)
            if not state:
                continue

            strategy = state.strategy
            for param, original_value in originals.items():
                if hasattr(strategy, param):
                    setattr(strategy, param, original_value)
                    reverted += 1

        self._threshold_widen_active = False
        self._original_thresholds.clear()

        if reverted > 0:
            self._heal_actions.append(
                f"reverted_threshold_widening ({reverted} params)"
            )
            logger.info(
                "Self-heal: reverted %d threshold params to original values "
                "(trade executed, drought over)",
                reverted,
            )

    # ── Self-Cleaning ───────────────────────────────────────────────

    async def _run_self_clean(self) -> None:
        """Periodic cleanup: WAL checkpoint, stale data, log rotation."""
        actions = []

        # 1. SQLite WAL checkpoint
        wal_path = Path(f"{self._db_path}-wal")
        if wal_path.exists() and wal_path.stat().st_size > WAL_CHECKPOINT_BYTES:
            try:
                conn = sqlite3.connect(str(self._db_path), timeout=10.0)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.close()
                actions.append("wal_checkpoint")
                logger.info("Self-clean: WAL checkpoint completed")
            except Exception as e:
                logger.warning(f"WAL checkpoint failed: {e}")

        # 2. Stale regime history
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=10.0)
            cursor = conn.execute("SELECT COUNT(*) FROM regime_history")
            count = cursor.fetchone()[0]
            if count > STALE_REGIME_ROWS_MAX:
                conn.execute(
                    "DELETE FROM regime_history WHERE id NOT IN "
                    "(SELECT id FROM regime_history ORDER BY timestamp DESC LIMIT ?)",
                    (STALE_REGIME_ROWS_KEEP,),
                )
                conn.commit()
                deleted = count - STALE_REGIME_ROWS_KEEP
                actions.append(f"purged_{deleted}_stale_regime_rows")
                logger.info("Self-clean: purged %d stale regime history rows", deleted)
            conn.close()
        except Exception:
            pass  # Table may not exist yet

        # 3. Stale Captain's Log entries in Supabase
        if self._bot.dashboard and self._bot.dashboard._available:
            try:
                client = self._bot.dashboard._client
                if client:
                    # Count entries
                    resp = await client.get(
                        self._bot.dashboard._rest_url("captains_log"),
                        params={"select": "id", "order": "created_at.desc"},
                        headers=self._bot.dashboard._get_headers(),
                    )
                    if resp.status_code == 200:
                        entries = resp.json()
                        if len(entries) > STALE_CAPTAINS_LOG_MAX:
                            # Get IDs to delete (oldest ones beyond the keep limit)
                            ids_to_keep = [e["id"] for e in entries[:STALE_CAPTAINS_LOG_KEEP]]
                            if ids_to_keep:
                                # Delete entries not in the keep list
                                keep_str = ",".join(str(i) for i in ids_to_keep)
                                await client.delete(
                                    f"{self._bot.dashboard._rest_url('captains_log')}"
                                    f"?id=not.in.({keep_str})",
                                    headers=self._bot.dashboard._get_headers(),
                                )
                                actions.append("trimmed_captains_log")
                                logger.info("Self-clean: trimmed Captain's Log to %d entries", STALE_CAPTAINS_LOG_KEEP)
            except Exception:
                pass

        # 4. Log rotation
        if self._log_path and self._log_path.exists():
            if self._log_path.stat().st_size > LOG_ROTATE_BYTES:
                rotated_path = self._log_path.with_suffix(".log.1")
                try:
                    if rotated_path.exists():
                        rotated_path.unlink()
                    self._log_path.rename(rotated_path)
                    # Create fresh log file
                    self._log_path.touch()
                    actions.append("rotated_log")
                    logger.info("Self-clean: rotated log file (was >100MB)")
                except Exception as e:
                    logger.warning(f"Log rotation failed: {e}")

        if actions:
            logger.info("Self-clean actions: %s", ", ".join(actions))

    # ── Status Reporting ────────────────────────────────────────────

    def _compute_overall_status(self, status: HealthStatus) -> str:
        """Determine overall health status from individual checks."""
        critical_conditions = [
            status.api_status.startswith("error") and self._api_consecutive_failures >= 5,
            status.cycles_with_zero_opportunities >= ZERO_OPP_HEAL_CYCLES,
        ]

        degraded_conditions = [
            status.api_status != "connected",
            status.cycles_with_zero_opportunities >= ZERO_OPP_WARN_CYCLES,
            status.market_data_status == "unavailable",
            status.db_wal_size_mb > 40.0,
            status.log_size_mb > 80.0,
            status.governor_confidence <= 0.1 and self._total_cycles > 10,
        ]

        if any(critical_conditions):
            return "critical"
        if any(degraded_conditions):
            return "degraded"
        return "healthy"

    async def _push_health_status(self, status: HealthStatus) -> None:
        """Push health status to Supabase (singleton row, always PATCH id=1)."""
        dashboard = self._bot.dashboard
        if not dashboard or not dashboard._available:
            self._supabase_consecutive_failures += 1
            return

        try:
            data = status.to_dict()
            # JSONB columns accept dicts directly via PostgREST
            success = await dashboard._patch(
                "health_status", "id=eq.1", data
            )
            if success:
                self._supabase_consecutive_failures = 0
            else:
                self._supabase_consecutive_failures += 1
        except Exception as e:
            self._supabase_consecutive_failures += 1
            logger.debug(f"Health status push failed: {e}")

    async def _alert_if_degraded(self, status: HealthStatus) -> None:
        """Write alerts to Captain's Log and dashboard for degraded/critical status."""
        if status.overall_status == "healthy":
            return

        # Captain's Log alert
        captains_log = self._bot.captains_log
        if captains_log:
            from .captains_log import NarrationEvent, EventPriority

            priority = (
                EventPriority.CRITICAL
                if status.overall_status == "critical"
                else EventPriority.SIGNIFICANT
            )

            summary_parts = []
            if status.cycles_with_zero_opportunities >= ZERO_OPP_WARN_CYCLES:
                summary_parts.append(
                    f"Zero opportunities for {status.cycles_with_zero_opportunities} cycles."
                )
            if status.api_status != "connected":
                summary_parts.append(f"API: {status.api_status}.")
            if status.market_data_status == "unavailable":
                summary_parts.append("No market data available.")
            if self._threshold_widen_active:
                summary_parts.append("Auto-widened thresholds active.")

            if summary_parts:
                captains_log.record_event(NarrationEvent(
                    event_type="health_alert",
                    priority=priority,
                    timestamp=datetime.now(timezone.utc),
                    summary=f"Health: {status.overall_status}. " + " ".join(summary_parts),
                    strategy=None,
                    metadata={"overall_status": status.overall_status},
                ))

        # Dashboard log
        dashboard = self._bot.dashboard
        if dashboard and dashboard._available:
            level = "ERROR" if status.overall_status == "critical" else "WARNING"
            await dashboard.push_log(
                f"Health monitor: {status.overall_status} — "
                f"{status.cycles_with_zero_opportunities} zero-opp cycles, "
                f"API={status.api_status}",
                level=level,
                strategy="health_monitor",
            )

    def _recent_errors(self) -> List[str]:
        """Return the 20 most recent errors."""
        return self._error_buffer[-20:]
