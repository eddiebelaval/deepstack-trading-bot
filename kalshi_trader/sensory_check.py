"""
Sensory Check — 3-Tier Remediation System for Dae

Runs inside the bot on a configurable interval (default: 15 min).
Checks the 7 "senses" and routes failures through 3 remediation tiers:

  Tier 1: Self-healing (in-process, immediate)
    Auto-fixes for known recoverable issues. Supabase reconnect,
    Telegram reconnect, cycle rate normalization. Known-absent services
    (IBKR, CryExc, Polymarket) are downgraded to informational.

  Tier 2: Claude-routed remediation (external script)
    Persistent criticals (2+ consecutive checks) write a remediation
    request to Supabase. An external launchd script polls this table,
    spawns a Claude Code session on a feature branch, creates a PR,
    and notifies Eddie via Telegram.

  Tier 3: Human escalation (Telegram)
    Only fires for issues that truly need Eddie: API key rotation,
    balance top-up, strategy decisions. Includes actionable context
    and deduplication to prevent alert fatigue.

Senses:
  SIGHT     - Market data feed (Kalshi API reachable, series returning markets)
  ACTION    - Authenticated API access (RSA-PSS signing, balance)
  THOUGHT   - Governance engine, config, mind files
  FORESIGHT - Forward signal bridge series coverage
  MEMORY    - SQLite journal + Supabase sync health
  VOICE     - Telegram bot + dashboard sync liveness
  BODY      - Process metrics (uptime, cycle rate, log freshness)
"""

import asyncio
import json
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


# ── Remediation tier classification ──────────────────────────────────

class RemediationTier:
    """Issue routing classification."""
    AUTO_FIX = "auto_fix"          # Tier 1: fix in-process immediately
    CLAUDE_ROUTE = "claude_route"  # Tier 2: needs code change, route to Claude
    HUMAN_REQUIRED = "human_required"  # Tier 3: needs Eddie


# Known-absent services that should not trigger criticals.
# These are optional integrations — their absence is expected.
_OPTIONAL_SERVICES = {"ibkr", "cryexc", "polymarket", "fred"}


@dataclass
class SenseResult:
    """Result of a single sensory check."""
    sense: str
    name: str
    passed: bool
    detail: str = ""
    critical: bool = False
    auto_fixed: bool = False
    tier: str = ""  # Remediation tier for failures


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
    def claude_routable(self) -> List[SenseResult]:
        return [r for r in self.results if not r.passed and r.tier == RemediationTier.CLAUDE_ROUTE]

    @property
    def human_required(self) -> List[SenseResult]:
        return [r for r in self.results if not r.passed and r.tier == RemediationTier.HUMAN_REQUIRED]

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
                {"sense": r.sense, "name": r.name, "detail": r.detail, "tier": r.tier}
                for r in self.critical_failures
            ],
            "warnings": [
                {"sense": r.sense, "name": r.name, "detail": r.detail, "tier": r.tier}
                for r in self.warnings
            ],
            "auto_fix_actions": self.auto_fix_actions,
            "claude_routable": [
                {"sense": r.sense, "name": r.name, "detail": r.detail}
                for r in self.claude_routable
            ],
            "human_required": [
                {"sense": r.sense, "name": r.name, "detail": r.detail}
                for r in self.human_required
            ],
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
    Runtime sensory monitor with 3-tier remediation.

    Tier 1: Auto-fix recoverable failures in-process.
    Tier 2: Route persistent code issues to Claude via Supabase.
    Tier 3: Escalate human-required issues to Eddie via Telegram.
    """

    def __init__(self, bot: Any, interval_seconds: int = 900):
        self._bot = bot
        self._interval = interval_seconds
        self._last_check: float = 0
        self._last_report: Optional[SensoryReport] = None
        self._consecutive_critical: int = 0
        # Deduplication: track which issues have been alerted to avoid spam
        self._alerted_issues: Dict[str, float] = {}  # issue_key -> last_alert_time
        self._alert_cooldown = 3600  # 1 hour between repeat alerts for same issue
        # Track which issues have been routed to Claude
        self._claude_routed_issues: Dict[str, float] = {}  # issue_key -> route_time
        self._claude_route_cooldown = 7200  # 2 hours between re-routing same issue

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

        # Push full report to Supabase (for Tier 2 polling + dashboard)
        await self._push_report(report)

        # Tier 2: Route to Claude if criticals persist
        if self._consecutive_critical >= 2:
            await self._route_to_claude(report)

        # Tier 3: Alert Eddie only for human-required issues
        await self._alert_human(report)

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
        # Check config-based URL first, then env var
        config_url = ""
        if hasattr(self._bot, "config"):
            config_url = getattr(self._bot.config, "api_base_url", "") or ""
        api_url = os.getenv("KALSHI_API_URL", "") or config_url

        report.results.append(SenseResult(
            sense="SIGHT", name="Kalshi API URL",
            passed=bool(api_url),
            detail=api_url[:50] if api_url else "NOT SET",
            critical=not bool(api_url),
            tier=RemediationTier.HUMAN_REQUIRED if not api_url else "",
        ))

        if not api_url:
            return

        # API reachability (use bot's existing client if available)
        try:
            if self._bot.client:
                bal = await self._bot.client.get_balance()
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
                        tier=RemediationTier.CLAUDE_ROUTE if r.status_code != 200 else "",
                    ))
        except Exception as e:
            report.results.append(SenseResult(
                sense="SIGHT", name="Kalshi API reachable",
                passed=False, detail=str(e)[:100],
                critical=True,
                tier=RemediationTier.CLAUDE_ROUTE,
            ))

        # Market data from last scan
        scanned = getattr(self._bot, "_last_scanned_markets", [])
        market_count = len(scanned) if scanned else 0
        report.results.append(SenseResult(
            sense="SIGHT", name="Markets in last scan",
            passed=market_count > 0,
            detail=f"{market_count} markets",
            critical=False,
        ))

    # ── ACTION: Order Execution ──────────────────────────────────────

    async def _check_action(self, report: SensoryReport) -> None:
        """Check authenticated API access and balance."""
        api_key = os.getenv("KALSHI_API_KEY", "")
        config_key = getattr(self._bot.config, "api_key_id", "") if hasattr(self._bot, "config") else ""
        has_key = bool(api_key) or bool(config_key)
        key_hint = (
            f"***{api_key[-4:]}" if api_key
            else (f"config:***{config_key[-4:]}" if config_key else "NOT SET")
        )
        report.results.append(SenseResult(
            sense="ACTION", name="API key configured",
            passed=has_key,
            detail=key_hint,
            critical=not has_key,
            tier=RemediationTier.HUMAN_REQUIRED if not has_key else "",
        ))

        # Check balance via bot client
        if self._bot.client:
            try:
                bal = await self._bot.client.get_balance()
                balance_usd = bal["balance"] if isinstance(bal, dict) else (bal / 100 if bal > 1 else bal)
                report.results.append(SenseResult(
                    sense="ACTION", name="Authenticated API access",
                    passed=True,
                    detail=f"Balance: ${balance_usd:.2f}",
                ))

                # Balance thresholds
                if balance_usd <= 0:
                    tier = RemediationTier.HUMAN_REQUIRED
                    critical = True
                elif balance_usd < 10:
                    tier = RemediationTier.HUMAN_REQUIRED
                    critical = False
                else:
                    tier = ""
                    critical = False

                report.results.append(SenseResult(
                    sense="ACTION", name="Balance sufficient",
                    passed=balance_usd > 1,
                    detail=f"${balance_usd:.2f}",
                    critical=critical,
                    tier=tier,
                ))
            except Exception as e:
                report.results.append(SenseResult(
                    sense="ACTION", name="Authenticated API access",
                    passed=False, detail=str(e)[:100],
                    critical=True,
                    tier=RemediationTier.CLAUDE_ROUTE,
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
        config = getattr(self._bot, "config", None)
        report.results.append(SenseResult(
            sense="THOUGHT", name="Config loaded",
            passed=config is not None,
            detail="Loaded" if config else "MISSING",
            critical=config is None,
            tier=RemediationTier.CLAUDE_ROUTE if config is None else "",
        ))

        # Anthropic API key (for AI analysis — optional, not critical)
        has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY", ""))
        report.results.append(SenseResult(
            sense="THOUGHT", name="ANTHROPIC_API_KEY",
            passed=has_anthropic,
            detail="Configured" if has_anthropic else "MISSING — AI analysis disabled",
            tier=RemediationTier.HUMAN_REQUIRED if not has_anthropic else "",
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
                tier=RemediationTier.CLAUDE_ROUTE if file_count == 0 else "",
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
                tier=RemediationTier.CLAUDE_ROUTE,
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
                tier=RemediationTier.CLAUDE_ROUTE,
            ))
            return

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
            tier=RemediationTier.CLAUDE_ROUTE if active_count == 0 else "",
        ))

    # ── MEMORY: Data Persistence ─────────────────────────────────────

    async def _check_memory(self, report: SensoryReport) -> None:
        """Check SQLite journal and Supabase sync health."""
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
                    tier=RemediationTier.CLAUDE_ROUTE,
                ))
        else:
            report.results.append(SenseResult(
                sense="MEMORY", name="SQLite journal",
                passed=False, detail="DB file not found",
                critical=True,
                tier=RemediationTier.CLAUDE_ROUTE,
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
                tier=RemediationTier.AUTO_FIX,
            ))
            # TIER 1 AUTO-FIX: reconnect Supabase
            if dashboard:
                try:
                    await dashboard.connect()
                    if getattr(dashboard, "_available", False):
                        report.auto_fix_actions.append("Reconnected Supabase dashboard sync")
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
                                tier=RemediationTier.AUTO_FIX,
                            ))
                except Exception as e:
                    report.results.append(SenseResult(
                        sense="VOICE", name="Telegram bot alive",
                        passed=False, detail=str(e)[:80],
                        tier=RemediationTier.AUTO_FIX,
                    ))
            else:
                report.results.append(SenseResult(
                    sense="VOICE", name="Telegram bot",
                    passed=False, detail="No token configured",
                    tier=RemediationTier.HUMAN_REQUIRED,
                ))
        else:
            report.results.append(SenseResult(
                sense="VOICE", name="Telegram bot",
                passed=False, detail="Not available",
                tier=RemediationTier.AUTO_FIX,
            ))
            # TIER 1 AUTO-FIX: reconnect Telegram
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
        health_monitor = getattr(self._bot, "health_monitor", None)
        if health_monitor:
            uptime = health_monitor.uptime_seconds
            hours = uptime / 3600
            report.results.append(SenseResult(
                sense="BODY", name="Uptime",
                passed=True,
                detail=f"{hours:.1f}h",
            ))

            # Cycle rate — only meaningful after 5 min of uptime
            total_cycles = getattr(health_monitor, "_total_cycles", 0)
            if total_cycles > 0 and uptime > 300:
                cycles_per_min = total_cycles / (uptime / 60)
                report.results.append(SenseResult(
                    sense="BODY", name="Cycle rate",
                    passed=cycles_per_min > 0.3,
                    detail=f"{cycles_per_min:.1f}/min ({total_cycles} total)",
                    critical=cycles_per_min < 0.1,
                    tier=RemediationTier.CLAUDE_ROUTE if cycles_per_min < 0.1 else "",
                ))
            elif uptime <= 300:
                report.results.append(SenseResult(
                    sense="BODY", name="Cycle rate",
                    passed=True,
                    detail=f"Warming up ({int(uptime)}s uptime)",
                ))

        # Running mode
        paper = getattr(self._bot, "paper_trade", True)
        report.results.append(SenseResult(
            sense="BODY", name="Running mode",
            passed=True,
            detail="LIVE" if not paper else "PAPER",
        ))

    # ── Tier 1: Self-Healing ─────────────────────────────────────────
    # (Auto-fix actions are embedded in each check method above)

    # ── Tier 2: Claude-Routed Remediation ────────────────────────────

    async def _route_to_claude(self, report: SensoryReport) -> None:
        """Write remediation request to Supabase for the external script to pick up."""
        routable = report.claude_routable
        if not routable:
            return

        # Build issue key for deduplication
        issue_key = "|".join(f"{r.sense}:{r.name}" for r in routable)
        now = time.time()

        # Check cooldown — don't re-route the same issue too quickly
        last_routed = self._claude_routed_issues.get(issue_key, 0)
        if now - last_routed < self._claude_route_cooldown:
            logger.debug(f"Claude route cooldown active for: {issue_key}")
            return

        self._claude_routed_issues[issue_key] = now

        dashboard = getattr(self._bot, "dashboard", None)
        if not dashboard or not getattr(dashboard, "_available", False):
            logger.warning("Cannot route to Claude — Supabase unavailable")
            return

        remediation_request = {
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "consecutive_critical": self._consecutive_critical,
            "failures": [
                {
                    "sense": r.sense,
                    "name": r.name,
                    "detail": r.detail,
                }
                for r in routable
            ],
            "full_report": report.to_dict(),
            "prompt": self._build_claude_prompt(routable),
        }

        try:
            await dashboard._upsert(
                "remediation_queue",
                remediation_request,
            )
            logger.info(
                f"Tier 2: Routed {len(routable)} issues to Claude remediation queue"
            )
        except Exception as e:
            # Fall back to log entry if table doesn't exist yet
            logger.warning(f"Claude route failed (table may not exist): {e}")
            try:
                await dashboard.push_log(
                    f"REMEDIATION NEEDED: {len(routable)} issues require code fix. "
                    + "; ".join(f"{r.sense}/{r.name}: {r.detail}" for r in routable),
                    level="ERROR",
                    strategy="remediation",
                )
            except Exception:
                pass

    def _build_claude_prompt(self, failures: List[SenseResult]) -> str:
        """Build the prompt that Claude Code will receive."""
        lines = [
            "Dae trading bot sensory check detected persistent failures.",
            "Investigate and fix the following issues:",
            "",
        ]
        for f in failures:
            lines.append(f"- [{f.sense}] {f.name}: {f.detail}")

        lines.extend([
            "",
            "Context:",
            f"- Bot repo: ~/clawd/projects/kalshi-trading/",
            f"- Sensory check: kalshi_trader/sensory_check.py",
            f"- Consecutive critical checks: {self._consecutive_critical}",
            "",
            "Instructions:",
            "1. Read the relevant source files to understand the failure",
            "2. Fix the root cause (not just suppress the warning)",
            "3. Test the fix if possible",
            "4. Create a commit on a feature branch",
        ])
        return "\n".join(lines)

    # ── Tier 3: Human Escalation (Telegram) ──────────────────────────

    async def _alert_human(self, report: SensoryReport) -> None:
        """Send Telegram alert only for human-required issues."""
        telegram = getattr(self._bot, "telegram_bridge", None)
        if not telegram or not getattr(telegram, "is_available", False):
            return

        now = time.time()
        lines = []

        # Tier 3: Issues that need Eddie
        human_issues = report.human_required
        if human_issues:
            # Dedup check — only alert for NEW issues or after cooldown
            new_issues = []
            for r in human_issues:
                issue_key = f"{r.sense}:{r.name}"
                last_alert = self._alerted_issues.get(issue_key, 0)
                if now - last_alert >= self._alert_cooldown:
                    new_issues.append(r)
                    self._alerted_issues[issue_key] = now

            if new_issues:
                lines.append("[Dae] ACTION NEEDED")
                lines.append("")
                for r in new_issues:
                    action = self._get_human_action(r)
                    lines.append(f"  {r.sense}: {r.name}")
                    lines.append(f"    Status: {r.detail}")
                    lines.append(f"    Action: {action}")
                    lines.append("")

        # Also mention auto-fixes (informational, no action needed)
        if report.auto_fix_actions:
            if lines:
                lines.append("---")
            lines.append("Auto-fixed:")
            for action in report.auto_fix_actions:
                lines.append(f"  > {action}")

        # Mention Claude-routed issues (informational)
        routable = report.claude_routable
        if routable and self._consecutive_critical >= 2:
            if lines:
                lines.append("---")
            lines.append(f"Routed to Claude ({len(routable)} issues):")
            for r in routable:
                lines.append(f"  {r.sense}: {r.name}")

        if lines:
            try:
                await telegram._send_message("\n".join(lines))
            except Exception:
                pass

    def _get_human_action(self, result: SenseResult) -> str:
        """Return actionable instruction for a human-required issue."""
        name_lower = result.name.lower()

        if "api key" in name_lower:
            return "Check API key in config.yaml or .env — may need rotation"
        if "balance" in name_lower:
            return "Fund the Kalshi account — balance too low to trade"
        if "anthropic" in name_lower:
            return "Add ANTHROPIC_API_KEY to .env for AI analysis"
        if "telegram" in name_lower and "token" in result.detail.lower():
            return "Configure DAE_TELEGRAM_TOKEN in .env"
        if "kalshi api url" in name_lower:
            return "Set KALSHI_API_URL in .env"

        return "Investigate manually — this issue requires human judgment"

    # ── Reporting ────────────────────────────────────────────────────

    async def _push_report(self, report: SensoryReport) -> None:
        """Push sensory report to Supabase for dashboard and Tier 2 polling."""
        dashboard = getattr(self._bot, "dashboard", None)
        if not dashboard or not getattr(dashboard, "_available", False):
            return

        try:
            # Push summary log
            await dashboard.push_log(
                report.summary_line(),
                level="ERROR" if report.critical_failures else (
                    "WARNING" if report.warnings else "INFO"
                ),
                strategy="sensory_check",
            )

            # Push full report to health status for Tier 2 script to read
            report_data = {
                "id": 1,
                "sensory_report": json.dumps(report.to_dict()),
                "sensory_status": report.overall_status,
                "consecutive_critical": self._consecutive_critical,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await dashboard._upsert(
                    "health_status", report_data, on_conflict="id"
                )
            except Exception:
                pass  # health_status table may not have sensory columns yet

        except Exception as e:
            logger.debug(f"Sensory report push failed: {e}")
