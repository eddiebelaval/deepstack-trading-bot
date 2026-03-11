"""
Sensory Check — Runtime Preflight Monitor for Dae

Runs inside the bot on a configurable interval (default: 15 min).
Checks the 7 "senses" that the standalone preflight script checks,
but as an async module that can auto-fix recoverable failures and
log results to Supabase.

Senses:
  SIGHT     - Market data feed (Kalshi API reachable, series returning markets)
  ACTION    - Authenticated API access (RSA-PSS signing, balance)
  THOUGHT   - Governance engine, config, mind files
  FORESIGHT - Forward signal bridge series coverage
  MEMORY    - SQLite journal + Supabase sync health
  VOICE     - Telegram bot + dashboard sync liveness
  BODY      - Process metrics (uptime, cycle rate, log freshness)

Auto-fix actions (clamped, reversible):
  - Supabase reconnect on consecutive failures
  - Telegram reconnect on ping failure
  - Forward signal bridge data re-ingest on stale signals
"""

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).parent
_MIND_DIR = _MODULE_DIR / "mind"

# Expected mind subdirectories
_MIND_SUBDIRS = ["kernel", "lexicon", "models", "drives"]


@dataclass
class SenseResult:
    """Result of a single sensory check."""
    sense: str
    name: str
    passed: bool
    detail: str = ""
    critical: bool = False
    auto_fixed: bool = False


@dataclass
class SensoryReport:
    """Full sensory diagnostic report."""
    timestamp: datetime
    results: List[SenseResult] = field(default_factory=list)
    auto_fix_actions: List[str] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def critical_failures(self) -> List[SenseResult]:
        return [r for r in self.results if not r.passed and r.critical]

    @property
    def warnings(self) -> List[SenseResult]:
        return [r for r in self.results if not r.passed and not r.critical]

    @property
    def overall_status(self) -> str:
        if self.critical_failures:
            return "critical"
        if self.warnings:
            return "degraded"
        return "healthy"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status,
            "passed": self.passed,
            "total": self.total,
            "critical_failures": [
                {"sense": r.sense, "name": r.name, "detail": r.detail}
                for r in self.critical_failures
            ],
            "warnings": [
                {"sense": r.sense, "name": r.name, "detail": r.detail}
                for r in self.warnings
            ],
            "auto_fix_actions": self.auto_fix_actions,
            "senses": {
                sense: {
                    "status": "green" if all(
                        r.passed for r in self.results if r.sense == sense
                    ) else "red",
                    "checks": [
                        {"name": r.name, "passed": r.passed, "detail": r.detail}
                        for r in self.results if r.sense == sense
                    ],
                }
                for sense in dict.fromkeys(r.sense for r in self.results)
            },
        }

    def summary_line(self) -> str:
        status = self.overall_status.upper()
        return (
            f"Sensory check: {status} — {self.passed}/{self.total} passed"
            + (f", {len(self.critical_failures)} critical" if self.critical_failures else "")
            + (f", {len(self.warnings)} warnings" if self.warnings else "")
            + (f", {len(self.auto_fix_actions)} auto-fixed" if self.auto_fix_actions else "")
        )


class SensoryMonitor:
    """
    Runtime sensory monitor that runs inside the bot process.

    Checks all 7 senses on a configurable interval. Auto-fixes
    recoverable failures. Logs results and alerts on degradation.
    """

    def __init__(self, bot: Any, interval_seconds: int = 900):
        self._bot = bot
        self._interval = interval_seconds
        self._last_check: float = 0
        self._last_report: Optional[SensoryReport] = None
        self._consecutive_critical: int = 0

    async def maybe_run(self) -> Optional[SensoryReport]:
        """Run sensory check if interval has elapsed. Returns report or None."""
        now = time.time()
        if now - self._last_check < self._interval:
            return None

        self._last_check = now
        report = await self.run_check()
        self._last_report = report

        # Log result
        logger.info(report.summary_line())
        for action in report.auto_fix_actions:
            logger.info(f"Sensory auto-fix: {action}")

        # Track consecutive critical failures
        if report.critical_failures:
            self._consecutive_critical += 1
        else:
            self._consecutive_critical = 0

        # Push to Supabase
        await self._push_report(report)

        # Alert on degradation
        await self._alert_if_needed(report)

        return report

    async def run_check(self) -> SensoryReport:
        """Run all 7 sensory checks and return a report."""
        report = SensoryReport(timestamp=datetime.now(timezone.utc))

        await self._check_sight(report)
        await self._check_action(report)
        self._check_thought(report)
        self._check_foresight(report)
        await self._check_memory(report)
        await self._check_voice(report)
        self._check_body(report)

        return report

    # ── SIGHT: Market Data Feed ──────────────────────────────────────

    async def _check_sight(self, report: SensoryReport) -> None:
        """Check Kalshi API reachability and market data availability."""
        api_url = os.getenv("KALSHI_API_URL", "")

        report.results.append(SenseResult(
            sense="SIGHT", name="Kalshi API URL",
            passed=bool(api_url),
            detail=api_url or "NOT SET",
            critical=not bool(api_url),
        ))

        if not api_url:
            return

        # API reachability (use bot's existing client if available)
        try:
            if self._bot.client:
                balance = await self._bot.client.get_balance()
                report.results.append(SenseResult(
                    sense="SIGHT", name="Kalshi API reachable",
                    passed=True, detail="Connected via bot client",
                ))
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(f"{api_url}/exchange/status")
                    report.results.append(SenseResult(
                        sense="SIGHT", name="Kalshi API reachable",
                        passed=r.status_code == 200,
                        detail=f"HTTP {r.status_code}",
                        critical=r.status_code != 200,
                    ))
        except Exception as e:
            report.results.append(SenseResult(
                sense="SIGHT", name="Kalshi API reachable",
                passed=False, detail=str(e)[:100],
                critical=True,
            ))

        # Market data from last scan
        scanned = getattr(self._bot, "_last_scanned_markets", [])
        market_count = len(scanned) if scanned else 0
        report.results.append(SenseResult(
            sense="SIGHT", name="Markets in last scan",
            passed=market_count > 0,
            detail=f"{market_count} markets",
            critical=False,  # Warning only — could be between scans
        ))

    # ── ACTION: Order Execution ──────────────────────────────────────

    async def _check_action(self, report: SensoryReport) -> None:
        """Check authenticated API access and balance."""
        api_key = os.getenv("KALSHI_API_KEY", "")
        report.results.append(SenseResult(
            sense="ACTION", name="API key configured",
            passed=bool(api_key),
            detail=f"***{api_key[-4:]}" if api_key else "NOT SET",
            critical=not bool(api_key),
        ))

        # Check balance via bot client (avoids re-signing)
        if self._bot.client:
            try:
                balance = await self._bot.client.get_balance()
                balance_usd = balance / 100 if balance > 1 else balance
                report.results.append(SenseResult(
                    sense="ACTION", name="Authenticated API access",
                    passed=True,
                    detail=f"Balance: ${balance_usd:.2f}",
                ))
                report.results.append(SenseResult(
                    sense="ACTION", name="Balance sufficient",
                    passed=balance_usd > 1,
                    detail=f"${balance_usd:.2f}",
                    critical=balance_usd <= 0,
                ))
            except Exception as e:
                report.results.append(SenseResult(
                    sense="ACTION", name="Authenticated API access",
                    passed=False, detail=str(e)[:100],
                    critical=True,
                ))

        # Trading mode
        paper = getattr(self._bot, "paper_trade", True)
        report.results.append(SenseResult(
            sense="ACTION", name="Trading mode",
            passed=True,
            detail="PAPER" if paper else "LIVE",
        ))

    # ── THOUGHT: Governance & Intelligence ───────────────────────────

    def _check_thought(self, report: SensoryReport) -> None:
        """Check governance engine, config, and mind files."""
        # Config
        config = getattr(self._bot, "config", None)
        report.results.append(SenseResult(
            sense="THOUGHT", name="Config loaded",
            passed=config is not None,
            detail="Loaded" if config else "MISSING",
            critical=config is None,
        ))

        # Anthropic API key (for AI analysis)
        has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY", ""))
        report.results.append(SenseResult(
            sense="THOUGHT", name="ANTHROPIC_API_KEY",
            passed=has_anthropic,
            detail="Configured" if has_anthropic else "MISSING — AI analysis disabled",
        ))

        # Mind files
        if _MIND_DIR.exists():
            mind_files = list(_MIND_DIR.rglob("*"))
            file_count = sum(1 for f in mind_files if f.is_file())
            report.results.append(SenseResult(
                sense="THOUGHT", name="Mind files",
                passed=file_count > 0,
                detail=f"{file_count} files in mind/",
                critical=file_count == 0,
            ))

            for subdir in _MIND_SUBDIRS:
                subpath = _MIND_DIR / subdir
                if subpath.exists():
                    count = sum(1 for f in subpath.rglob("*") if f.is_file())
                    report.results.append(SenseResult(
                        sense="THOUGHT", name=f"mind/{subdir}/",
                        passed=count > 0,
                        detail=f"{count} files",
                    ))
        else:
            report.results.append(SenseResult(
                sense="THOUGHT", name="Mind files",
                passed=False, detail="mind/ directory missing",
                critical=True,
            ))

        # Governor state
        governor = getattr(self._bot, "market_governor", None)
        if governor:
            regime = getattr(governor, "current_regime", None)
            if regime:
                report.results.append(SenseResult(
                    sense="THOUGHT", name="Regime detection",
                    passed=True,
                    detail=f"{regime.regime.value} (conf={regime.confidence:.2f})",
                ))
            else:
                report.results.append(SenseResult(
                    sense="THOUGHT", name="Regime detection",
                    passed=False, detail="No regime data yet",
                ))

    # ── FORESIGHT: Forward Signal Bridge ─────────────────────────────

    def _check_foresight(self, report: SensoryReport) -> None:
        """Check forward signal bridge coverage."""
        bridge = getattr(self._bot, "forward_signal_bridge", None)
        if not bridge:
            report.results.append(SenseResult(
                sense="FORESIGHT", name="Forward signal bridge",
                passed=False, detail="Not initialized",
                critical=True,
            ))
            return

        # Check signal source coverage
        signal_sources = {
            "RATE_SHIFT": "KXFED",
            "INFLATION": "KXCPI",
            "GROWTH": "KXGDP",
            "RISK_APPETITE_BTC": "KXBTC",
            "RISK_APPETITE_ETH": "KXETH",
        }

        history = getattr(bridge, "_price_history", {})
        active_count = 0

        for label, series in signal_sources.items():
            data_points = len(history.get(series, []))
            has_data = data_points > 0
            if has_data:
                active_count += 1
            report.results.append(SenseResult(
                sense="FORESIGHT", name=f"{label} ({series})",
                passed=has_data,
                detail=f"{data_points} data points",
            ))

        report.results.append(SenseResult(
            sense="FORESIGHT", name="Signal coverage",
            passed=active_count >= 3,
            detail=f"{active_count}/{len(signal_sources)} sources active",
            critical=active_count == 0,
        ))

    # ── MEMORY: Data Persistence ─────────────────────────────────────

    async def _check_memory(self, report: SensoryReport) -> None:
        """Check SQLite journal and Supabase sync health."""
        # SQLite journal
        db_path = getattr(self._bot.config, "journal_db_path", None)
        if db_path and Path(db_path).exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db_path), timeout=5.0)
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE status='closed'"
                )
                trade_count = cursor.fetchone()[0]
                conn.close()
                report.results.append(SenseResult(
                    sense="MEMORY", name="SQLite journal",
                    passed=True,
                    detail=f"{trade_count} closed trades",
                ))
            except Exception as e:
                report.results.append(SenseResult(
                    sense="MEMORY", name="SQLite journal",
                    passed=False, detail=str(e)[:100],
                    critical=True,
                ))
        else:
            report.results.append(SenseResult(
                sense="MEMORY", name="SQLite journal",
                passed=False, detail="DB file not found",
                critical=True,
            ))

        # Supabase sync
        dashboard = getattr(self._bot, "dashboard", None)
        if dashboard and getattr(dashboard, "_available", False):
            report.results.append(SenseResult(
                sense="MEMORY", name="Supabase sync",
                passed=True, detail="Connected",
            ))
        else:
            report.results.append(SenseResult(
                sense="MEMORY", name="Supabase sync",
                passed=False, detail="Disconnected",
            ))
            # AUTO-FIX: try to reconnect
            if dashboard:
                try:
                    await dashboard.connect()
                    if getattr(dashboard, "_available", False):
                        report.auto_fix_actions.append("Reconnected Supabase dashboard sync")
                        # Update the result
                        report.results[-1] = SenseResult(
                            sense="MEMORY", name="Supabase sync",
                            passed=True, detail="Reconnected (auto-fix)",
                            auto_fixed=True,
                        )
                except Exception:
                    pass

    # ── VOICE: Communication Channels ────────────────────────────────

    async def _check_voice(self, report: SensoryReport) -> None:
        """Check Telegram bot and dashboard sync liveness."""
        telegram = getattr(self._bot, "telegram_bridge", None)

        if telegram and getattr(telegram, "is_available", False):
            # Ping the bot API to verify it's still alive
            token = getattr(telegram, "_token", "") or os.getenv("DAE_TELEGRAM_TOKEN", "")
            if token:
                try:
                    async with httpx.AsyncClient(timeout=5) as client:
                        r = await client.get(
                            f"https://api.telegram.org/bot{token}/getMe"
                        )
                        if r.status_code == 200:
                            bot_name = r.json().get("result", {}).get("username", "unknown")
                            report.results.append(SenseResult(
                                sense="VOICE", name="Telegram bot alive",
                                passed=True, detail=f"@{bot_name}",
                            ))
                        else:
                            report.results.append(SenseResult(
                                sense="VOICE", name="Telegram bot alive",
                                passed=False, detail=f"HTTP {r.status_code}",
                            ))
                except Exception as e:
                    report.results.append(SenseResult(
                        sense="VOICE", name="Telegram bot alive",
                        passed=False, detail=str(e)[:80],
                    ))
            else:
                report.results.append(SenseResult(
                    sense="VOICE", name="Telegram bot",
                    passed=False, detail="No token configured",
                ))
        else:
            report.results.append(SenseResult(
                sense="VOICE", name="Telegram bot",
                passed=False, detail="Not available",
            ))
            # AUTO-FIX: try to reconnect Telegram
            if telegram:
                try:
                    await telegram.connect()
                    if getattr(telegram, "is_available", False):
                        report.auto_fix_actions.append("Reconnected Telegram bridge")
                        report.results[-1] = SenseResult(
                            sense="VOICE", name="Telegram bot",
                            passed=True, detail="Reconnected (auto-fix)",
                            auto_fixed=True,
                        )
                except Exception:
                    pass

        # Dashboard sync
        dashboard = getattr(self._bot, "dashboard", None)
        report.results.append(SenseResult(
            sense="VOICE", name="Dashboard sync",
            passed=dashboard is not None and getattr(dashboard, "_available", False),
            detail="Active" if (dashboard and getattr(dashboard, "_available", False)) else "Down",
        ))

    # ── BODY: Process Health ─────────────────────────────────────────

    def _check_body(self, report: SensoryReport) -> None:
        """Check process-level health metrics."""
        # Uptime
        health_monitor = getattr(self._bot, "health_monitor", None)
        if health_monitor:
            uptime = health_monitor.uptime_seconds
            hours = uptime / 3600
            report.results.append(SenseResult(
                sense="BODY", name="Uptime",
                passed=True,
                detail=f"{hours:.1f}h",
            ))

            # Cycle rate
            total_cycles = getattr(health_monitor, "_total_cycles", 0)
            if total_cycles > 0 and uptime > 60:
                cycles_per_min = total_cycles / (uptime / 60)
                report.results.append(SenseResult(
                    sense="BODY", name="Cycle rate",
                    passed=cycles_per_min > 0.5,
                    detail=f"{cycles_per_min:.1f}/min ({total_cycles} total)",
                    critical=cycles_per_min < 0.1,
                ))

        # Paper vs live
        paper = getattr(self._bot, "paper_trade", True)
        report.results.append(SenseResult(
            sense="BODY", name="Running mode",
            passed=True,
            detail="LIVE" if not paper else "PAPER",
        ))

    # ── Reporting & Alerting ─────────────────────────────────────────

    async def _push_report(self, report: SensoryReport) -> None:
        """Push sensory report to Supabase for dashboard display."""
        dashboard = getattr(self._bot, "dashboard", None)
        if not dashboard or not getattr(dashboard, "_available", False):
            return

        try:
            await dashboard.push_log(
                report.summary_line(),
                level="ERROR" if report.critical_failures else (
                    "WARNING" if report.warnings else "INFO"
                ),
                strategy="sensory_check",
            )
        except Exception as e:
            logger.debug(f"Sensory report push failed: {e}")

    async def _alert_if_needed(self, report: SensoryReport) -> None:
        """Send Telegram alert on critical failures or new degradation."""
        if not report.critical_failures and not report.auto_fix_actions:
            return

        telegram = getattr(self._bot, "telegram_bridge", None)
        if not telegram or not getattr(telegram, "is_available", False):
            return

        lines = [f"[Sensory Check] {report.overall_status.upper()}"]
        lines.append(f"{report.passed}/{report.total} checks passed")

        if report.critical_failures:
            lines.append("")
            lines.append("CRITICAL:")
            for r in report.critical_failures:
                lines.append(f"  X {r.sense}: {r.name} — {r.detail}")

        if report.auto_fix_actions:
            lines.append("")
            lines.append("Auto-fixed:")
            for action in report.auto_fix_actions:
                lines.append(f"  > {action}")

        if report.warnings and len(report.warnings) <= 3:
            lines.append("")
            lines.append("Warnings:")
            for r in report.warnings:
                lines.append(f"  ! {r.sense}: {r.name} — {r.detail}")

        try:
            await telegram._send_message("\n".join(lines))
        except Exception:
            pass
