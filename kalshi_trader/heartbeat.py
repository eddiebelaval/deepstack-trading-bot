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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from . import consciousness
from .graduation_gate import GraduationGate
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
        logger.debug("Heartbeat: Telegram bridge connected")

    def set_graduation_gate(self, gate: GraduationGate) -> None:
        """Set the graduation gate reference for go-live tracking."""
        self._graduation_gate = gate
        logger.debug("Heartbeat: graduation gate connected")

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

                        alert_lines = [
                            f"GRADUATION: {sector_label} — All thresholds passed.",
                            f"Trades: {report.paper_trades_closed}",
                            f"Win Rate: {report.win_rate:.0%}",
                            f"Max Drawdown: {report.max_drawdown_pct:.1f}%",
                        ]
                        if report_path:
                            alert_lines.append(f"Report: {report_path}")
                        alert_lines.append("Ready for go-live review.")

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
        self._state["last_ai_summary"] = response.get("summary", "")

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

        # Parse JSON — handle markdown fences if Haiku wraps them
        clean = response_text
        if clean.startswith("```"):
            # Strip ```json ... ```
            lines = clean.splitlines()
            clean = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )

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
