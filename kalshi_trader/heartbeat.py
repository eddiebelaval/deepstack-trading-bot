"""
Heartbeat Engine — Hybrid Self-Regulation for DeepStack

Two-tier monitoring system:
  Tier 1 (every cycle):  Deterministic Python checks — P&L breach, consecutive
                         losses, win rate degradation, stale positions. Free.
  Tier 2 (every 30 min): AI interpretation of HEARTBEAT.md standing orders
                         against live bot state via Haiku (~$0.01/cycle).

Standing orders live in mind/HEARTBEAT.md. Eddie edits that file to change
what Dae watches for — no code changes needed.

Runtime state persists to heartbeat-state.json (gitignored) so alert flags
and timestamps survive restarts.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

import yaml

from . import consciousness
from .graduation_gate import GraduationGate, STRATEGY_ASSET_CLASS
from .graduation_report import generate_graduation_report

logger = logging.getLogger(__name__)

HAIKU = "claude-haiku-4-5-20251001"

# Path constants
_MODULE_DIR = Path(__file__).parent
_STATE_PATH = _MODULE_DIR.parent / "heartbeat-state.json"
_STANDING_ORDERS_PATH = _MODULE_DIR / "mind" / "HEARTBEAT.md"

# Arsenal refresh: auto-populate lexicon arsenal files on 6-hour interval
_ARSENAL_REFRESH_SECONDS = 21600  # 6 hours
_ARSENAL_PATH = _MODULE_DIR / "mind" / "lexicon" / "arsenal" / "tv-top-performers.md"

# Auto-research: gap analysis + targeted scrape on 24-hour interval
_AUTO_RESEARCH_SECONDS = 86400  # 24 hours


class HeartbeatEngine:
    """
    Hybrid self-regulation engine for Dae.

    Runs deterministic checks every trading cycle and AI-powered
    standing order evaluation on a configurable interval.
    """

    def __init__(self, bot: Any, config: dict):
        """
        Initialize HeartbeatEngine.

        Args:
            bot: KalshiTradingBot instance (for accessing subsystems).
            config: heartbeat section from config.yaml.
        """
        self._bot = bot
        self._config = config
        self._telegram = None  # Set via set_telegram()
        self._claude_client: Optional[httpx.AsyncClient] = None

        # Tier 2 timing
        self._ai_interval: int = config.get("ai_interval_seconds", 1800)
        self._last_ai_heartbeat: float = 0

        # Alert thresholds from config
        self._pnl_threshold: float = config.get("pnl_alert_threshold", -5.0)
        self._consec_loss_alert: int = config.get("consecutive_loss_alert", 3)
        self._win_rate_threshold: float = config.get("win_rate_alert_threshold", 0.35)
        self._telegram_alerts: bool = config.get("telegram_alerts", True)
        self._lessons_write: bool = config.get("lessons_write", True)
        self._max_lessons_lines: int = config.get("max_lessons_lines", 50)

        # Auto-research config
        self._auto_research_enabled: bool = config.get("auto_research_enabled", True)
        self._auto_research_interval: int = config.get(
            "auto_research_interval_seconds", _AUTO_RESEARCH_SECONDS
        )
        self._last_auto_research: float = time.time()  # Wait full interval before first run

        # Graduation gate (optional, set via set_graduation_gate())
        self._graduation_gate: Optional[GraduationGate] = None

        # Tier 3: Self-repair engine (optional, invokes Claude Code CLI)
        self._self_repair = None
        if config.get("self_repair_enabled", True):
            try:
                from .self_repair import SelfRepairEngine
                self._self_repair = SelfRepairEngine()
                logger.info("Self-repair engine initialized (Tier 3)")
            except Exception as e:
                logger.warning("Self-repair init failed (non-fatal): %s", e)

        # Load persisted state
        self._state: dict = self._load_state()
        self._today: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Initialize Claude client for AI heartbeat
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            self._claude_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )

        logger.info(
            "Heartbeat engine initialized "
            f"(AI interval: {self._ai_interval}s, "
            f"P&L threshold: ${self._pnl_threshold}, "
            f"AI enabled: {self._claude_client is not None})"
        )

    def set_telegram(self, telegram_bridge: Any) -> None:
        """Set the Telegram bridge reference for sending alerts."""
        self._telegram = telegram_bridge
        if self._self_repair:
            self._self_repair._telegram = telegram_bridge
        logger.debug("Heartbeat: Telegram bridge connected")

    def set_graduation_gate(self, gate: GraduationGate) -> None:
        """Set the graduation gate reference for go-live tracking."""
        self._graduation_gate = gate
        logger.debug("Heartbeat: graduation gate connected")

    def _promote_sector_to_live(self, sector_key: str) -> List[str]:
        """
        Flip paper_trade=false on all strategies in a graduated sector.

        Updates runtime strategy config AND persists to config.yaml.
        Returns list of strategy names that were promoted.
        """
        promoted: List[str] = []

        # Find strategies belonging to this sector
        strategies_in_sector = [
            name for name, ac in STRATEGY_ASSET_CLASS.items()
            if ac == sector_key
        ]
        if not strategies_in_sector:
            return promoted

        # 1. Runtime flip — update strategy instances in the bot's strategy_manager
        strategy_manager = getattr(self._bot, "strategy_manager", None)
        if strategy_manager:
            for strat_name in strategies_in_sector:
                state = strategy_manager._strategies.get(strat_name)
                if state and hasattr(state.strategy, "paper_trade"):
                    if state.strategy.paper_trade:
                        state.strategy.paper_trade = False
                        promoted.append(strat_name)
                        logger.info(
                            "AUTO-PROMOTE: %s paper_trade=False (sector %s graduated)",
                            strat_name, sector_key,
                        )

        # 2. Persist to config.yaml so it survives restart
        if promoted:
            self._persist_promotion_to_yaml(promoted)

        return promoted

    def _persist_promotion_to_yaml(self, strategy_names: List[str]) -> None:
        """Update config.yaml to set paper_trade: false for promoted strategies."""
        config_path = Path(self._bot.config.journal_db_path).parent / "config.yaml"
        if not config_path.exists():
            logger.warning("Cannot persist promotion — config.yaml not found at %s", config_path)
            return

        try:
            raw = config_path.read_text()
            for name in strategy_names:
                # Replace paper_trade: true in the strategy's config block.
                # Pattern: find "- name: {name}" then the next "paper_trade: true" after it.
                # Use line-by-line replacement scoped to the right strategy block.
                lines = raw.split("\n")
                in_strategy = False
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped == f"- name: {name}":
                        in_strategy = True
                    elif in_strategy and stripped.startswith("- name:"):
                        break  # Next strategy block
                    elif in_strategy and "paper_trade: true" in stripped:
                        lines[i] = line.replace(
                            "paper_trade: true",
                            "paper_trade: false        # AUTO-PROMOTED by graduation gate",
                        )
                        in_strategy = False
                        break
                raw = "\n".join(lines)

            config_path.write_text(raw)
            logger.info("Persisted promotion to %s for: %s", config_path, strategy_names)
        except Exception as e:
            logger.warning("Failed to persist promotion to config.yaml: %s", e)

    async def close(self) -> None:
        """Clean up HTTP client."""
        if self._claude_client:
            await self._claude_client.aclose()
            self._claude_client = None

    # ── Tier 1: Deterministic Checks (every cycle) ───────────────────

    async def tick(self, bot_state: dict) -> None:
        """
        Called every trading cycle. Runs deterministic checks
        and triggers AI heartbeat on interval.

        Args:
            bot_state: Dict with balance, daily_pnl, open_positions,
                       regime, active_strategies.
        """
        alerts: List[str] = []

        # Date rollover — reset daily alert flags
        self._check_date_rollover()

        # Check 1: Daily P&L breach
        daily_pnl = bot_state.get("daily_pnl", 0)
        if daily_pnl < self._pnl_threshold and not self._state.get("pnl_alert_sent"):
            alerts.append(
                f"${daily_pnl:.2f} daily P&L — below ${self._pnl_threshold:.2f} threshold. "
                f"Balance: ${bot_state.get('balance', 0):.2f}."
            )
            self._state["pnl_alert_sent"] = True

        # Check 2: Consecutive losses per strategy
        consec_alerts = self._check_consecutive_losses()
        alerts.extend(consec_alerts)

        # Check 3: Strategy win rate degradation
        winrate_alerts = self._check_win_rates()
        alerts.extend(winrate_alerts)

        # Check 4: Strategy error rate monitor (auto-disable broken data feeds)
        error_alerts = self._check_strategy_error_rates()
        alerts.extend(error_alerts)

        # Check 5: Position sizing invariant (catch oversized positions)
        sizing_alerts = self._check_position_sizing_invariants(bot_state)
        alerts.extend(sizing_alerts)

        # Send alerts via Telegram
        if alerts and self._telegram_alerts:
            await self._send_telegram_alert(alerts)

        # Graduation gate check (Tier 1 — free, deterministic)
        # Evaluates ALL sectors and generates HTML report on graduation.
        self._last_graduation_report = None
        if self._graduation_gate:
            try:
                all_reports = self._graduation_gate.evaluate_all()
                # Cache Kalshi report for AI heartbeat context
                self._last_graduation_report = all_reports.get("kalshi")

                # Track per-sector graduation notifications
                graduated_sectors = self._state.get("graduated_sectors", [])

                for sector_key, report in all_reports.items():
                    sector_label = sector_key.upper()
                    if report.ready and sector_label not in graduated_sectors:
                        # Generate HTML report
                        report_path = generate_graduation_report(
                            sector=sector_label,
                            report=report,
                            db_path=self._graduation_gate._db_path,
                        )

                        # Auto-promote strategies in this sector from paper to live
                        promoted = self._promote_sector_to_live(sector_key)

                        alert_lines = [
                            f"GRADUATION: {sector_label} — All thresholds passed.",
                            f"Trades: {report.paper_trades_closed}",
                            f"Win Rate: {report.win_rate:.0%}",
                            f"Max Drawdown: {report.max_drawdown_pct:.1f}%",
                        ]
                        if report_path:
                            alert_lines.append(f"Report: {report_path}")
                        if promoted:
                            alert_lines.append(
                                f"AUTO-PROMOTED to LIVE: {', '.join(promoted)}"
                            )
                            alert_lines.append("Strategies now placing REAL orders.")
                        else:
                            alert_lines.append("No strategies to promote (already live or not loaded).")

                        await self._send_telegram_alert(
                            alert_lines,
                            header=f"[Graduation — {sector_label}]",
                        )

                        graduated_sectors.append(sector_label)
                        self._state["graduated_sectors"] = graduated_sectors

                # Backward compat: set graduation_notified if kalshi is ready
                kalshi = all_reports.get("kalshi")
                if kalshi and kalshi.ready:
                    self._state["graduation_notified"] = True

            except Exception as e:
                logger.info(f"Heartbeat: graduation check failed: {e}")

        # Tier 2: AI heartbeat on interval
        now = time.time()
        if (
            self._claude_client
            and now - self._last_ai_heartbeat >= self._ai_interval
        ):
            await self._ai_heartbeat(bot_state)
            self._last_ai_heartbeat = now

        # Persist state
        self._save_state()

    def _check_consecutive_losses(self) -> List[str]:
        """Check circuit breaker state for consecutive loss streaks."""
        alerts = []
        breakers = getattr(self._bot, "_strategy_circuit_breakers", {})
        alerted_strategies = self._state.get("consec_loss_alerted", {})

        for name, cb in breakers.items():
            consec = cb.get("consecutive_losses", 0)
            if consec >= self._consec_loss_alert:
                # Only alert once per streak (reset when streak breaks)
                last_alerted = alerted_strategies.get(name, 0)
                if consec > last_alerted:
                    alerts.append(
                        f"{name}: {consec} consecutive losses. "
                        f"Total P&L: {cb.get('total_pnl_cents', 0) / 100:.2f}."
                    )
                    alerted_strategies[name] = consec
            else:
                # Streak broken — reset alert flag
                alerted_strategies.pop(name, None)

        self._state["consec_loss_alerted"] = alerted_strategies
        return alerts

    def _check_win_rates(self) -> List[str]:
        """Check blended win rates from PerformanceTracker."""
        alerts = []
        tracker = getattr(self._bot, "performance_tracker", None)
        if not tracker:
            return alerts

        alerted_strategies = self._state.get("winrate_alerted", {})
        strategy_manager = getattr(self._bot, "strategy_manager", None)
        if not strategy_manager:
            return alerts

        for name in strategy_manager._strategies:
            try:
                health = tracker.evaluate_health(name)
                if (
                    health.blended_win_rate < self._win_rate_threshold
                    and health.observed_trade_count >= 10  # Need data confidence
                    and name not in alerted_strategies
                ):
                    alerts.append(
                        f"{name}: win rate {health.blended_win_rate:.0%} "
                        f"(below {self._win_rate_threshold:.0%} threshold). "
                        f"EV: {health.blended_ev_cents:.1f}c. "
                        f"Based on {health.observed_trade_count} trades."
                    )
                    alerted_strategies[name] = True
                elif health.blended_win_rate >= self._win_rate_threshold:
                    alerted_strategies.pop(name, None)
            except Exception as e:
                logger.debug(f"Heartbeat: win rate check failed for {name}: {e}")

        self._state["winrate_alerted"] = alerted_strategies
        return alerts

    def _check_date_rollover(self) -> None:
        """Reset daily alert flags on date change."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._today:
            logger.info(f"Heartbeat: date rollover {self._today} -> {today}")
            self._today = today
            self._state["pnl_alert_sent"] = False
            self._state["consec_loss_alerted"] = {}
            self._state["winrate_alerted"] = {}
            self._state["error_rate_disabled"] = []
            self._state["consecutive_parse_errors"] = 0

    # ── Tier 1.5: Self-Healing Checks ───────────────────────────────

    def _check_strategy_error_rates(self) -> List[str]:
        """
        Auto-disable strategies with high error rates and zero successful trades.

        Checks per-strategy error counters (populated by the trading loop).
        If a strategy has >50 errors and 0 trades in the current session,
        auto-disable it and alert via Telegram.

        This would have caught the 2,409 IBKR subscription error firehose.
        """
        alerts = []
        strategy_manager = getattr(self._bot, "strategy_manager", None)
        if not strategy_manager:
            return alerts
        error_counts = getattr(strategy_manager, "_error_counts", {})
        trade_counts = getattr(strategy_manager, "_trade_counts", {})

        already_disabled = self._state.get("error_rate_disabled", [])

        for name, error_count in error_counts.items():
            if name in already_disabled:
                continue
            trades = trade_counts.get(name, 0)
            if error_count >= 50 and trades == 0:
                # Auto-disable the strategy
                state = strategy_manager._strategies.get(name)
                if state and state.enabled:
                    state.enabled = False
                    already_disabled.append(name)
                    alert_msg = (
                        f"AUTO-DISABLED '{name}': {error_count} errors, "
                        f"0 trades this session. Data feed likely unavailable."
                    )
                    alerts.append(alert_msg)
                    logger.warning(f"Heartbeat: {alert_msg}")

        self._state["error_rate_disabled"] = already_disabled
        return alerts

    def _check_position_sizing_invariants(self, bot_state: dict) -> List[str]:
        """
        Hard invariant check: no single open position should exceed
        50% of the relevant account balance. If violated, alert immediately.

        This would have caught the SPY $670 position on $230 account.
        """
        alerts = []
        strategy_manager = getattr(self._bot, "strategy_manager", None)
        if not strategy_manager:
            return alerts

        balance = bot_state.get("balance", 0)
        if balance <= 0:
            return alerts

        # Check live positions from the trade journal
        journal = getattr(self._bot, "trade_journal", None)
        if not journal:
            return alerts

        try:
            import sqlite3
            db_path = getattr(self._bot.config, "journal_db_path", None)
            if not db_path:
                return alerts
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT strategy, market_ticker, entry_price_cents, contracts "
                "FROM trades WHERE status='open' AND is_paper=0"
            )
            for strategy, ticker, entry_cents, contracts in cursor:
                position_value = (entry_cents * contracts) / 100.0
                if position_value > balance * 0.50:
                    alert_msg = (
                        f"POSITION SIZING VIOLATION: {ticker} [{strategy}] "
                        f"${position_value:.2f} > 50% of ${balance:.2f} balance"
                    )
                    alerts.append(alert_msg)
                    logger.warning(f"Heartbeat: {alert_msg}")
            conn.close()
        except Exception as e:
            logger.debug(f"Heartbeat: position invariant check failed: {e}")

        return alerts

    async def startup_self_test(self) -> List[str]:
        """
        Run on boot. Validates DAE's own state before entering the trading loop.

        Checks:
        1. Enabled strategies have working data feeds
        2. Config vs dashboard alignment
        3. Open exposure within limits
        4. AI heartbeat layer is functional

        Returns list of issues found (empty = healthy).
        """
        issues = []
        strategy_manager = getattr(self._bot, "strategy_manager", None)

        # Check 1: Config-disabled strategies should not be enabled
        config_disabled = getattr(self._bot, "_config_disabled_strategies", set())
        if strategy_manager:
            for name in config_disabled:
                state = strategy_manager._strategies.get(name)
                if state and state.enabled:
                    issues.append(
                        f"CONFIG VIOLATION: '{name}' is config-disabled but running. Forcing off."
                    )
                    state.enabled = False

        # Check 2: Open exposure vs limit
        risk = getattr(self._bot, "risk", None)
        if risk:
            current_exposure = sum(risk.open_positions.values())
            max_exposure = getattr(risk.config, "max_open_exposure", 25)
            if current_exposure > max_exposure * 1.5:
                issues.append(
                    f"EXPOSURE WARNING: ${current_exposure:.2f} open > "
                    f"${max_exposure:.2f} limit (150% threshold)"
                )

        # Check 3: AI heartbeat layer
        if not self._claude_client:
            issues.append("AI HEARTBEAT DEGRADED: No ANTHROPIC_API_KEY — running deterministic-only")
        elif self._state.get("last_ai_summary") == "Parse error":
            consecutive_parse_errors = self._state.get("consecutive_parse_errors", 0)
            if consecutive_parse_errors >= 3:
                issues.append(
                    f"AI HEARTBEAT FAILING: {consecutive_parse_errors} consecutive parse errors"
                )

        if issues:
            logger.warning("Startup self-test found %d issue(s):", len(issues))
            for issue in issues:
                logger.warning("  - %s", issue)
            if self._telegram_alerts:
                await self._send_telegram_alert(issues, header="[Startup Self-Test]")
        else:
            logger.info("Startup self-test: all checks passed")

        return issues

    # ── Tier 2: AI Heartbeat (every 30 min) ──────────────────────────

    async def _ai_heartbeat(self, bot_state: dict) -> None:
        """
        AI-powered evaluation of standing orders against live state.

        Reads HEARTBEAT.md + bot state, asks Haiku to evaluate.
        Can trigger: Telegram alerts, lessons.md writes, advisory logs.
        Also refreshes lexicon arsenal files on 6-hour interval.
        """
        # Arsenal refresh check (non-blocking — don't delay heartbeat evaluation)
        asyncio.create_task(self._maybe_refresh_arsenal())

        # Auto-research gap check (non-blocking, 24h interval)
        asyncio.create_task(self._maybe_run_auto_research())

        standing_orders = self._read_standing_orders()
        if not standing_orders:
            logger.debug("Heartbeat: no standing orders found, skipping AI cycle")
            return

        context = self._build_heartbeat_context(bot_state, standing_orders)

        try:
            response = await self._call_claude(context)
        except Exception as e:
            logger.warning(f"Heartbeat AI cycle failed: {e}")
            return

        # Process structured response
        self._state["last_ai_heartbeat"] = datetime.now(timezone.utc).isoformat()
        summary = response.get("summary", "")
        if summary == "Parse error":
            self._state["consecutive_parse_errors"] = self._state.get("consecutive_parse_errors", 0) + 1
            logger.warning(
                "Heartbeat AI parse failure #%d — retrying with stripped prompt",
                self._state["consecutive_parse_errors"],
            )
            # Retry once with a minimal prompt that's harder for Haiku to mess up
            try:
                retry_resp = await self._call_claude_minimal(bot_state)
                if retry_resp.get("summary", "") != "Parse error":
                    response = retry_resp
                    summary = response.get("summary", "")
                    self._state["consecutive_parse_errors"] = 0
                    logger.info("Heartbeat AI retry succeeded: %s", summary)
            except Exception as e:
                logger.warning("Heartbeat AI retry also failed: %s", e)

            # Tier 3 escalation: if 3+ consecutive parse failures, invoke self-repair
            if self._state.get("consecutive_parse_errors", 0) >= 3 and self._self_repair:
                from .self_repair import RepairCategory
                asyncio.create_task(self._self_repair.repair_and_restart(
                    category=RepairCategory.HEARTBEAT_PARSE,
                    diagnosis=(
                        "AI heartbeat Haiku responses are not parsing as JSON. "
                        "The _call_claude method in heartbeat.py returns 'Parse error' "
                        "even after the JSON extraction fix. The model may be returning "
                        "a new response format that the parser doesn't handle."
                    ),
                    context=f"Last raw response was not parseable. Error count: {self._state['consecutive_parse_errors']}",
                    affected_files=["kalshi_trader/heartbeat.py"],
                ))
        else:
            self._state["consecutive_parse_errors"] = 0
        self._state["last_ai_summary"] = summary

        # Send Telegram alerts if any
        ai_alerts = response.get("alerts", [])
        if ai_alerts and response.get("telegram", False) and self._telegram_alerts:
            header = "[AI Heartbeat]"
            await self._send_telegram_alert(ai_alerts, header=header)

        # Write lessons if enabled
        ai_lessons = response.get("lessons", [])
        if ai_lessons and self._lessons_write:
            try:
                consciousness.write_lessons(
                    ai_lessons, max_lines=self._max_lessons_lines
                )
                logger.info(
                    f"Heartbeat: wrote {len(ai_lessons)} AI lesson(s) to lessons.md"
                )
            except Exception as e:
                logger.warning(f"Heartbeat: failed to write lessons: {e}")

        # Log recommendations (advisory only — never auto-applied)
        recommendations = response.get("recommendations", [])
        if recommendations:
            for rec in recommendations:
                logger.info(f"Heartbeat recommendation: {rec}")

        logger.info(
            f"AI heartbeat complete: {response.get('summary', 'no summary')} "
            f"(alerts={len(ai_alerts)}, lessons={len(ai_lessons)}, "
            f"recommendations={len(recommendations)})"
        )

    async def _maybe_refresh_arsenal(self) -> None:
        """Refresh lexicon arsenal files if stale (>6 hours) or missing."""
        try:
            needs_refresh = False
            if not _ARSENAL_PATH.exists():
                needs_refresh = True
                logger.info("Heartbeat: arsenal file missing, will populate")
            else:
                age = time.time() - _ARSENAL_PATH.stat().st_mtime
                if age > _ARSENAL_REFRESH_SECONDS:
                    needs_refresh = True
                    logger.info(f"Heartbeat: arsenal file is {age / 3600:.1f}h old, refreshing")

            if needs_refresh:
                import importlib
                import sys
                # Ensure project root is importable for scripts/ package
                project_root = str(_MODULE_DIR.parent)
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)
                mod = importlib.import_module("scripts.populate_lexicon_arsenal")
                success = await mod.populate_arsenal()
                if success:
                    logger.info("Heartbeat: arsenal refresh complete")
                else:
                    logger.debug("Heartbeat: arsenal refresh returned no data")

        except Exception as e:
            logger.debug(f"Heartbeat: arsenal refresh failed (non-critical): {e}")

    async def _maybe_run_auto_research(self) -> None:
        """Run auto-research gap analysis if stale (>24 hours)."""
        if not self._auto_research_enabled:
            return

        now = time.time()
        if now - self._last_auto_research < self._auto_research_interval:
            return

        try:
            import importlib
            import sys as _sys

            project_root = str(_MODULE_DIR.parent)
            if project_root not in _sys.path:
                _sys.path.insert(0, project_root)

            mod = importlib.import_module("scripts.auto_research_pipeline")
            gaps = await mod.discover_gaps()

            if "error" in gaps:
                logger.debug("Heartbeat: auto-research gap check returned error: %s", gaps["error"])
                return

            missing = gaps.get("missing_categories", [])
            thin = gaps.get("thin_categories", [])

            if missing or thin:
                logger.info(
                    "Heartbeat: auto-research found gaps — missing: %s, thin: %s",
                    missing, thin,
                )

                # Load auto_research config from yaml
                from kalshi_trader.config import load_yaml_config
                yaml_config = load_yaml_config()
                ar_config = yaml_config.get("auto_research", {})

                result = await mod.run_targeted_research(gaps, ar_config)

                # Alert via Telegram if new top performers found
                if result.get("arsenal_refreshed") and self._telegram_alerts and self._telegram:
                    scrapes = result.get("scrapes_triggered", 0)
                    await self._send_telegram_alert(
                        [f"Auto-research: {scrapes} targeted scrapes completed, arsenal refreshed."],
                        header="[Auto-Research]",
                    )
            else:
                logger.debug("Heartbeat: auto-research — no coverage gaps found")

            # Only mark completed after successful run
            self._last_auto_research = now

        except Exception as e:
            logger.debug("Heartbeat: auto-research failed (non-critical): %s", e)

    def _read_standing_orders(self) -> str:
        """Read HEARTBEAT.md standing orders. Fresh read every time (no cache)."""
        try:
            return _STANDING_ORDERS_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            logger.warning(f"Heartbeat: standing orders not found at {_STANDING_ORDERS_PATH}")
            return ""
        except Exception as e:
            logger.warning(f"Heartbeat: failed to read standing orders: {e}")
            return ""

    def _build_heartbeat_context(self, bot_state: dict, standing_orders: str) -> str:
        """Build the context string for the AI heartbeat prompt."""
        # Gather strategy health data
        strategy_health_lines = []
        tracker = getattr(self._bot, "performance_tracker", None)
        strategy_manager = getattr(self._bot, "strategy_manager", None)

        if tracker and strategy_manager:
            for name, state in strategy_manager._strategies.items():
                try:
                    health = tracker.evaluate_health(name)
                    cb = self._bot._strategy_circuit_breakers.get(name, {})
                    strategy_health_lines.append(
                        f"- {name}: enabled={state.enabled}, "
                        f"win_rate={health.blended_win_rate:.0%}, "
                        f"EV={health.blended_ev_cents:.1f}c, "
                        f"trades={health.observed_trade_count}, "
                        f"consec_losses={cb.get('consecutive_losses', 0)}, "
                        f"health={health.health_status}"
                    )
                except Exception:
                    strategy_health_lines.append(
                        f"- {name}: enabled={state.enabled}, health=unavailable"
                    )

        strategy_health = "\n".join(strategy_health_lines) or "No strategy data available"

        # Load recent lessons for context
        lessons = consciousness.load_memory()

        # Build regime info
        governor = getattr(self._bot, "market_governor", None)
        regime_info = "unknown"
        if governor:
            regime_snapshot = getattr(governor, "current_regime", None)
            if regime_snapshot:
                regime_info = f"{regime_snapshot.regime.value} (confidence={regime_snapshot.confidence:.2f})"

        # Graduation progress (reuses cached report from tick() to avoid double evaluation)
        graduation_section = ""
        if self._graduation_gate:
            try:
                graduation_section = (
                    "\n\n# Graduation Gate Progress\n\n"
                    + self._graduation_gate.get_progress_summary(
                        report=self._last_graduation_report
                    )
                )
            except Exception:
                pass

        context = f"""# Standing Orders

{standing_orders}

# Current Bot State

- Balance: ${bot_state.get('balance', 0):.2f}
- Daily P&L: ${bot_state.get('daily_pnl', 0):.2f}
- Open positions: {bot_state.get('open_positions', 0)}
- Market regime: {regime_info}
- Active strategies: {', '.join(bot_state.get('active_strategies', [])) or 'none'}
- Timestamp: {datetime.now(timezone.utc).isoformat()}

# Strategy Health

{strategy_health}

# Current Lessons (memory/lessons.md)

{lessons or 'No lessons recorded yet.'}

# Previous Heartbeat Summary

{self._state.get('last_ai_summary', 'First heartbeat — no previous data.')}{graduation_section}"""

        return context

    async def _call_claude(self, context: str) -> dict:
        """
        Call Haiku for heartbeat evaluation.

        Returns structured dict with: summary, alerts, lessons,
        recommendations, telegram.
        """
        if not self._claude_client:
            return {"summary": "AI client not available"}

        kernel = consciousness.load_kernel()

        system_prompt = f"""{kernel}

---

You are running a heartbeat self-check. Review the standing orders below
against the current bot state. Return a JSON object with:

- "summary": One-line status (max 100 chars)
- "alerts": Array of strings — things Eddie needs to know NOW. Be specific with numbers.
- "lessons": Array of strings — new insights to persist to lessons.md. Only include genuinely new learnings, not observations already in the current lessons.
- "recommendations": Array of strings — strategy adjustments to consider (advisory only, never auto-applied).
- "telegram": boolean — true if alerts are urgent enough to message Eddie.

Rules:
- Lead with numbers, not words.
- Only generate alerts for conditions that actually appear in the data.
- Don't alert on things that are normal or expected.
- Lessons should be concise (one line each) and actionable.
- If everything looks healthy, return empty arrays and telegram=false.
- Return ONLY valid JSON. No explanation outside the JSON."""

        resp = await self._claude_client.post(
            "https://api.anthropic.com/v1/messages",
            json={
                "model": HAIKU,
                "max_tokens": 500,
                "system": system_prompt,
                "messages": [{"role": "user", "content": context}],
            },
        )
        resp.raise_for_status()

        data = resp.json()
        response_text = data.get("content", [{}])[0].get("text", "").strip()

        # Parse JSON — handle markdown fences and preamble text from Haiku
        clean = response_text

        # Strip markdown code fences (```json ... ```)
        if "```" in clean:
            lines = clean.splitlines()
            clean = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )

        # Extract JSON object if Haiku added preamble/postscript text
        brace_start = clean.find("{")
        brace_end = clean.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            clean = clean[brace_start:brace_end + 1]

        # Normalize Python literals and trailing commas to valid JSON
        clean = re.sub(r'\bTrue\b', 'true', clean)
        clean = re.sub(r'\bFalse\b', 'false', clean)
        clean = re.sub(r'\bNone\b', 'null', clean)
        clean = re.sub(r',\s*([}\]])', r'\1', clean)

        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning(f"Heartbeat: failed to parse AI response: {response_text[:200]}")
            result = {"summary": "Parse error", "alerts": [], "lessons": [], "recommendations": [], "telegram": False}

        # Ensure all expected keys exist
        result.setdefault("summary", "")
        result.setdefault("alerts", [])
        result.setdefault("lessons", [])
        result.setdefault("recommendations", [])
        result.setdefault("telegram", False)

        return result

    async def _call_claude_minimal(self, bot_state: dict) -> dict:
        """
        Stripped-down AI heartbeat call for retry after parse failure.
        Uses a much simpler prompt to maximize JSON parsing success.
        """
        if not self._claude_client:
            return {"summary": "AI client not available"}

        balance = bot_state.get("balance", 0)
        daily_pnl = bot_state.get("daily_pnl", 0)
        positions = bot_state.get("open_positions", 0)
        regime = bot_state.get("regime", "unknown")

        simple_prompt = (
            f"Balance: ${balance:.2f}, Daily P&L: ${daily_pnl:.2f}, "
            f"Open positions: {positions}, Regime: {regime}. "
            f"Return ONLY a JSON object: "
            f'{{"summary": "one line status", "alerts": [], "lessons": [], '
            f'"recommendations": [], "telegram": false}}'
        )

        resp = await self._claude_client.post(
            "https://api.anthropic.com/v1/messages",
            json={
                "model": HAIKU,
                "max_tokens": 200,
                "messages": [{"role": "user", "content": simple_prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("content", [{}])[0].get("text", "").strip()

        # Extract JSON
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            text = text[brace_start:brace_end + 1]

        # Normalize Python literals and trailing commas to valid JSON
        text = re.sub(r'\bTrue\b', 'true', text)
        text = re.sub(r'\bFalse\b', 'false', text)
        text = re.sub(r'\bNone\b', 'null', text)
        text = re.sub(r',\s*([}\]])', r'\1', text)

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            result = {"summary": "Parse error", "alerts": [], "lessons": [], "recommendations": [], "telegram": False}

        result.setdefault("summary", "")
        result.setdefault("alerts", [])
        result.setdefault("lessons", [])
        result.setdefault("recommendations", [])
        result.setdefault("telegram", False)
        return result

    # ── Telegram ─────────────────────────────────────────────────────

    async def _send_telegram_alert(self, alerts: List[str], header: str = "[Heartbeat]") -> None:
        """Send alert messages to Eddie via Telegram."""
        if not self._telegram or not self._telegram.is_available:
            logger.info(f"Heartbeat alert (no Telegram): {alerts}")
            return

        message = f"{header}\n\n" + "\n".join(f"- {a}" for a in alerts)
        try:
            await self._telegram._send_message(message)
            logger.info(f"Heartbeat: sent {len(alerts)} alert(s) to Telegram")
        except Exception as e:
            logger.warning(f"Heartbeat: Telegram send failed: {e}")

    # ── State Persistence ────────────────────────────────────────────

    def _load_state(self) -> dict:
        """Load persisted heartbeat state from JSON file."""
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "pnl_alert_sent": False,
                "consec_loss_alerted": {},
                "winrate_alerted": {},
                "graduation_notified": False,
                "last_ai_heartbeat": None,
                "last_ai_summary": "",
            }

    def _save_state(self) -> None:
        """Persist heartbeat state to JSON file."""
        try:
            _STATE_PATH.write_text(
                json.dumps(self._state, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Heartbeat: failed to save state: {e}")
