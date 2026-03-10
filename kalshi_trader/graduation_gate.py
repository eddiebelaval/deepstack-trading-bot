"""
Graduation Gate — Go-Live Readiness Evaluation for DeepStack

Evaluates paper trading performance against defined thresholds to determine
readiness for live trading. Advisory only — Eddie flips the switch.

Supports per-asset-class evaluation:
  - Kalshi: prediction market trades (50 trades, 45% WR, regime gate)
  - Stocks: stock_momentum + crisis_alpha (30 trades, 50% WR)
  - Futures: futures_trend (20 trades, 45% WR)
  - Options: options_income + options_directional (15 trades, 60% WR)

Strategy-to-asset-class mapping:
  - kalshi: calibration_edge, mean_reversion, momentum, etc. (trades table, is_paper=1)
  - stocks: stock_momentum, crisis_alpha (stock_trades table)
  - futures: futures_trend (stock_trades table)
  - options: options_income, options_directional (stock_trades table)

Queries trade_journal.db directly via SQLite. No schema migration required —
regime linkage uses timestamp JOIN against regime_history.
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from .config import (
    GraduationConfig,
    GraduationFuturesConfig,
    GraduationOptionsConfig,
    GraduationStocksConfig,
)

logger = logging.getLogger(__name__)

# Map strategy names to asset classes
STRATEGY_ASSET_CLASS: Dict[str, str] = {
    "stock_momentum": "stocks",
    "crisis_alpha": "stocks",
    "futures_trend": "futures",
    "options_income": "options",
    "options_directional": "options",
}

# Strategies that live in stock_trades table (IBKR)
IBKR_STRATEGIES = {
    "stock_momentum", "crisis_alpha", "futures_trend",
    "options_income", "options_directional",
}


@dataclass
class GraduationReport:
    """Result of a graduation evaluation — current metrics vs thresholds."""

    # Current values
    paper_trades_closed: int = 0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    profitable_regimes: List[str] = field(default_factory=list)
    total_regimes_traded: List[str] = field(default_factory=list)

    # Thresholds
    min_trades: int = 50
    min_win_rate: float = 0.45
    max_drawdown: float = 15.0
    min_regimes: int = 2

    # Pass/fail per criterion
    trades_passed: bool = False
    win_rate_passed: bool = False
    drawdown_passed: bool = False
    regimes_passed: bool = False

    @property
    def ready(self) -> bool:
        """All four thresholds must pass for go-live readiness."""
        return (
            self.trades_passed
            and self.win_rate_passed
            and self.drawdown_passed
            and self.regimes_passed
        )


@dataclass
class AssetClassReport:
    """Result of an asset-class graduation evaluation (stocks/futures/options)."""

    asset_class: str = ""
    strategies: List[str] = field(default_factory=list)

    # Current values
    paper_trades_closed: int = 0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    profitable_days: int = 0
    avg_pnl_per_trade_cents: float = 0.0

    # Thresholds
    min_trades: int = 30
    min_win_rate: float = 0.50
    max_drawdown: float = 10.0
    min_profitable_days: int = 5
    min_avg_pnl_per_trade_cents: int = 50

    # Pass/fail per criterion
    trades_passed: bool = False
    win_rate_passed: bool = False
    drawdown_passed: bool = False
    profitable_days_passed: bool = False
    avg_pnl_passed: bool = False

    @property
    def ready(self) -> bool:
        """All thresholds must pass for go-live readiness."""
        return (
            self.trades_passed
            and self.win_rate_passed
            and self.drawdown_passed
            and self.profitable_days_passed
            and self.avg_pnl_passed
        )


class GraduationGate:
    """
    Evaluates paper trading readiness for live transition across all asset classes.

    Opens its own read-only SQLite connection to trade_journal.db.
    All queries are SELECT-only — never modifies data.
    """

    def __init__(
        self,
        config: GraduationConfig,
        journal_db_path: str,
        stocks_config: Optional[GraduationStocksConfig] = None,
        futures_config: Optional[GraduationFuturesConfig] = None,
        options_config: Optional[GraduationOptionsConfig] = None,
    ):
        self.config = config
        self.stocks_config = stocks_config
        self.futures_config = futures_config
        self.options_config = options_config
        self._db_path = journal_db_path

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only SQLite connection (no write locks, no WAL contention)."""
        conn = sqlite3.connect(
            f"file:{self._db_path}?mode=ro",
            uri=True,
            timeout=10,
        )
        conn.row_factory = sqlite3.Row
        return conn

    # ── Kalshi evaluation (existing logic) ──────────────────────────────

    def evaluate(self) -> GraduationReport:
        """
        Run all 4 threshold checks against closed Kalshi paper trades.

        Returns a GraduationReport with current values, thresholds,
        and pass/fail for each criterion.
        """
        report = GraduationReport(
            min_trades=self.config.min_paper_trades,
            min_win_rate=self.config.min_win_rate,
            max_drawdown=self.config.max_drawdown_pct,
            min_regimes=self.config.min_profitable_regimes,
        )

        conn = None
        try:
            conn = self._connect()

            # 1. Count closed paper trades + compute win rate
            rows = conn.execute(
                "SELECT pnl_cents FROM trades "
                "WHERE is_paper = 1 AND status = 'closed' AND pnl_cents IS NOT NULL "
                "ORDER BY updated_at ASC"
            ).fetchall()

            report.paper_trades_closed = len(rows)
            if rows:
                wins = sum(1 for r in rows if r["pnl_cents"] > 0)
                report.win_rate = wins / len(rows)

            report.trades_passed = report.paper_trades_closed >= self.config.min_paper_trades
            report.win_rate_passed = report.win_rate >= self.config.min_win_rate

            # 2. Compute max drawdown via running P&L peak (high-water mark)
            if rows:
                running_pnl = 0
                peak_pnl = 0
                max_drawdown_cents = 0
                for r in rows:
                    running_pnl += r["pnl_cents"]
                    peak_pnl = max(peak_pnl, running_pnl)
                    drawdown = peak_pnl - running_pnl
                    max_drawdown_cents = max(max_drawdown_cents, drawdown)

                paper_balance = self.config.paper_balance_cents
                if paper_balance > 0:
                    report.max_drawdown_pct = (max_drawdown_cents / paper_balance) * 100

            report.drawdown_passed = report.max_drawdown_pct <= self.config.max_drawdown_pct

            # 3. Regime linkage — find profitable regimes via timestamp JOIN
            regime_pnl = self._compute_regime_pnl(conn)
            report.total_regimes_traded = list(regime_pnl.keys())
            report.profitable_regimes = [
                regime for regime, pnl in regime_pnl.items() if pnl > 0
            ]
            report.regimes_passed = (
                len(report.profitable_regimes) >= self.config.min_profitable_regimes
            )

        except Exception as e:
            logger.warning(f"GraduationGate: Kalshi evaluation failed: {e}")
        finally:
            if conn:
                conn.close()

        return report

    def _compute_regime_pnl(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """
        Compute P&L per regime for closed paper trades.

        Links each trade to its active regime via the most recent
        regime_history entry at or before the trade's created_at timestamp.
        """
        query = """
            SELECT
                t.pnl_cents,
                (
                    SELECT rh.regime
                    FROM regime_history rh
                    WHERE datetime(rh.timestamp) <= datetime(t.created_at)
                    ORDER BY datetime(rh.timestamp) DESC
                    LIMIT 1
                ) AS trade_regime
            FROM trades t
            WHERE t.is_paper = 1
              AND t.status = 'closed'
              AND t.pnl_cents IS NOT NULL
        """
        try:
            rows = conn.execute(query).fetchall()
        except Exception as e:
            logger.warning(f"GraduationGate: regime query failed: {e}")
            return {}

        regime_pnl: Dict[str, int] = {}
        for r in rows:
            regime = r["trade_regime"]
            if regime:
                regime_pnl[regime] = regime_pnl.get(regime, 0) + r["pnl_cents"]

        return regime_pnl

    # ── Per-asset-class evaluation (stocks/futures/options) ─────────────

    def evaluate_asset_class(
        self,
        asset_class: str,
        config: Union[GraduationStocksConfig, GraduationFuturesConfig, GraduationOptionsConfig],
    ) -> AssetClassReport:
        """
        Evaluate graduation gate for a specific IBKR asset class.

        Reads from stock_trades table, filtering by strategy names
        that map to the given asset class.

        Args:
            asset_class: One of 'stocks', 'futures', 'options'
            config: The asset-class-specific graduation config
        """
        strategies = [
            name for name, ac in STRATEGY_ASSET_CLASS.items()
            if ac == asset_class
        ]

        report = AssetClassReport(
            asset_class=asset_class,
            strategies=strategies,
            min_trades=config.min_paper_trades,
            min_win_rate=config.min_win_rate,
            max_drawdown=config.max_drawdown_pct,
            min_profitable_days=config.min_profitable_days,
            min_avg_pnl_per_trade_cents=config.min_avg_pnl_per_trade_cents,
        )

        if not strategies:
            return report

        conn = None
        try:
            conn = self._connect()

            # Build strategy filter
            placeholders = ",".join("?" * len(strategies))

            # 1. Fetch closed trades for these strategies
            rows = conn.execute(
                f"SELECT pnl_cents, session_date FROM stock_trades "
                f"WHERE strategy IN ({placeholders}) "
                f"AND status = 'filled' AND pnl_cents IS NOT NULL "
                f"ORDER BY created_at ASC",
                strategies,
            ).fetchall()

            report.paper_trades_closed = len(rows)

            if rows:
                wins = sum(1 for r in rows if r["pnl_cents"] > 0)
                report.win_rate = wins / len(rows)

                total_pnl = sum(r["pnl_cents"] for r in rows)
                report.avg_pnl_per_trade_cents = total_pnl / len(rows)

            report.trades_passed = report.paper_trades_closed >= config.min_paper_trades
            report.win_rate_passed = report.win_rate >= config.min_win_rate
            report.avg_pnl_passed = report.avg_pnl_per_trade_cents >= config.min_avg_pnl_per_trade_cents

            # 2. Max drawdown via high-water mark
            if rows:
                running_pnl = 0
                peak_pnl = 0
                max_drawdown_cents = 0
                for r in rows:
                    running_pnl += r["pnl_cents"]
                    peak_pnl = max(peak_pnl, running_pnl)
                    drawdown = peak_pnl - running_pnl
                    max_drawdown_cents = max(max_drawdown_cents, drawdown)

                if config.paper_balance_cents > 0:
                    report.max_drawdown_pct = (max_drawdown_cents / config.paper_balance_cents) * 100

            report.drawdown_passed = report.max_drawdown_pct <= config.max_drawdown_pct

            # 3. Profitable days — count distinct session_dates with positive net P&L
            day_pnl_rows = conn.execute(
                f"SELECT session_date, SUM(pnl_cents) AS day_pnl FROM stock_trades "
                f"WHERE strategy IN ({placeholders}) "
                f"AND status = 'filled' AND pnl_cents IS NOT NULL "
                f"AND session_date IS NOT NULL "
                f"GROUP BY session_date",
                strategies,
            ).fetchall()

            report.profitable_days = sum(1 for r in day_pnl_rows if r["day_pnl"] > 0)
            report.profitable_days_passed = report.profitable_days >= config.min_profitable_days

        except Exception as e:
            logger.warning(f"GraduationGate: {asset_class} evaluation failed: {e}")
        finally:
            if conn:
                conn.close()

        return report

    # ── Aggregate evaluation ────────────────────────────────────────────

    def evaluate_all(self) -> Dict[str, Union[GraduationReport, AssetClassReport]]:
        """
        Evaluate all enabled graduation gates.

        Returns a dict keyed by asset class name:
          - 'kalshi': GraduationReport (always present if main config enabled)
          - 'stocks': AssetClassReport (if stocks_config enabled)
          - 'futures': AssetClassReport (if futures_config enabled)
          - 'options': AssetClassReport (if options_config enabled)
        """
        results: Dict[str, Union[GraduationReport, AssetClassReport]] = {}

        # Kalshi (always evaluated if this gate exists)
        results["kalshi"] = self.evaluate()

        if self.stocks_config and self.stocks_config.enabled:
            results["stocks"] = self.evaluate_asset_class("stocks", self.stocks_config)

        if self.futures_config and self.futures_config.enabled:
            results["futures"] = self.evaluate_asset_class("futures", self.futures_config)

        if self.options_config and self.options_config.enabled:
            results["options"] = self.evaluate_asset_class("options", self.options_config)

        return results

    # ── Summary formatting ──────────────────────────────────────────────

    def get_progress_summary(self, report: Optional[GraduationReport] = None) -> str:
        """
        Human-readable progress string for Telegram/logs.

        Shows all asset class gates, not just Kalshi.

        Args:
            report: Pre-computed Kalshi GraduationReport to avoid re-evaluation.
                    If None, calls evaluate_all() internally.
        """
        all_reports = self.evaluate_all()

        # Override kalshi report if one was passed in
        if report is not None:
            all_reports["kalshi"] = report

        lines: List[str] = []

        # Kalshi section
        kalshi_report = all_reports.get("kalshi")
        if isinstance(kalshi_report, GraduationReport):
            lines.extend(self._format_kalshi_report(kalshi_report))

        # Asset class sections
        for asset_class in ("stocks", "futures", "options"):
            ac_report = all_reports.get(asset_class)
            if isinstance(ac_report, AssetClassReport):
                if lines:
                    lines.append("")
                lines.extend(self._format_asset_class_report(ac_report))

        # Overall status
        all_ready = all(r.ready for r in all_reports.values())
        lines.append("")
        if all_ready:
            lines.append("OVERALL: ALL GATES PASSED")
        else:
            not_ready = [name for name, r in all_reports.items() if not r.ready]
            lines.append(f"OVERALL: NOT READY ({', '.join(not_ready)} pending)")

        return "\n".join(lines)

    def _format_kalshi_report(self, report: GraduationReport) -> List[str]:
        """Format Kalshi graduation report section."""

        def _bar(current: int, target: int, width: int = 15) -> str:
            pct = min(current / target, 1.0) if target > 0 else 0
            filled = int(pct * width)
            return "[" + "|" * filled + "." * (width - filled) + "]"

        def _tag(passed: bool) -> str:
            return "PASSED" if passed else "---"

        num_profitable = len(report.profitable_regimes)

        lines = [
            "Kalshi Graduation",
            "-" * 35,
        ]

        if report.trades_passed:
            lines.append(f"Trades:   {report.paper_trades_closed}/{report.min_trades}  [PASSED]")
        else:
            pct = min(report.paper_trades_closed / report.min_trades * 100, 100)
            lines.append(
                f"Trades:   {report.paper_trades_closed}/{report.min_trades}    "
                f"{_bar(report.paper_trades_closed, report.min_trades)}  {pct:.0f}%"
            )

        lines.append(f"Win Rate: {report.win_rate:.0%}/{report.min_win_rate:.0%}  [{_tag(report.win_rate_passed)}]")
        lines.append(f"Drawdown: {report.max_drawdown_pct:.1f}%/{report.max_drawdown:.0f}%   [{_tag(report.drawdown_passed)}]")

        if report.regimes_passed:
            lines.append(f"Regimes:  {num_profitable}/{report.min_regimes}  [PASSED]")
        else:
            pct = min(num_profitable / report.min_regimes * 100, 100)
            lines.append(
                f"Regimes:  {num_profitable}/{report.min_regimes}    "
                f"{_bar(num_profitable, report.min_regimes)}  {pct:.0f}%"
            )

        if report.total_regimes_traded:
            lines.append("")
            lines.append("Regimes traded: " + ", ".join(report.total_regimes_traded))
            if report.profitable_regimes:
                lines.append("Profitable in:  " + ", ".join(report.profitable_regimes))

        lines.append("")
        if report.ready:
            lines.append("Kalshi: READY — all thresholds passed")
        else:
            gaps = []
            if not report.trades_passed:
                gaps.append(f"{report.min_trades - report.paper_trades_closed} more trades")
            if not report.win_rate_passed:
                gaps.append(f"win rate needs {report.min_win_rate:.0%} (at {report.win_rate:.0%})")
            if not report.drawdown_passed:
                gaps.append(f"drawdown {report.max_drawdown_pct:.1f}% exceeds {report.max_drawdown:.0f}% cap")
            if not report.regimes_passed:
                needed = report.min_regimes - num_profitable
                gaps.append(f"{needed} more profitable regime{'s' if needed != 1 else ''}")
            lines.append("Kalshi: NOT READY")
            lines.append(f"Need: {', '.join(gaps)}")

        return lines

    def _format_asset_class_report(self, report: AssetClassReport) -> List[str]:
        """Format an asset-class graduation report section."""
        label = report.asset_class.capitalize()

        def _bar(current: int, target: int, width: int = 15) -> str:
            pct = min(current / target, 1.0) if target > 0 else 0
            filled = int(pct * width)
            return "[" + "|" * filled + "." * (width - filled) + "]"

        def _tag(passed: bool) -> str:
            return "PASSED" if passed else "---"

        lines = [
            f"{label} Graduation ({', '.join(report.strategies)})",
            "-" * 35,
        ]

        if report.trades_passed:
            lines.append(f"Trades:   {report.paper_trades_closed}/{report.min_trades}  [PASSED]")
        else:
            pct = min(report.paper_trades_closed / report.min_trades * 100, 100) if report.min_trades > 0 else 0
            lines.append(
                f"Trades:   {report.paper_trades_closed}/{report.min_trades}    "
                f"{_bar(report.paper_trades_closed, report.min_trades)}  {pct:.0f}%"
            )

        lines.append(f"Win Rate: {report.win_rate:.0%}/{report.min_win_rate:.0%}  [{_tag(report.win_rate_passed)}]")
        lines.append(f"Drawdown: {report.max_drawdown_pct:.1f}%/{report.max_drawdown:.0f}%   [{_tag(report.drawdown_passed)}]")

        if report.profitable_days_passed:
            lines.append(f"Prof Days: {report.profitable_days}/{report.min_profitable_days}  [PASSED]")
        else:
            pct = min(report.profitable_days / report.min_profitable_days * 100, 100) if report.min_profitable_days > 0 else 0
            lines.append(
                f"Prof Days: {report.profitable_days}/{report.min_profitable_days}    "
                f"{_bar(report.profitable_days, report.min_profitable_days)}  {pct:.0f}%"
            )

        lines.append(
            f"Avg P&L:  {report.avg_pnl_per_trade_cents:.0f}c/{report.min_avg_pnl_per_trade_cents}c  "
            f"[{_tag(report.avg_pnl_passed)}]"
        )

        lines.append("")
        if report.ready:
            lines.append(f"{label}: READY — all thresholds passed")
        else:
            gaps = []
            if not report.trades_passed:
                gaps.append(f"{report.min_trades - report.paper_trades_closed} more trades")
            if not report.win_rate_passed:
                gaps.append(f"win rate needs {report.min_win_rate:.0%} (at {report.win_rate:.0%})")
            if not report.drawdown_passed:
                gaps.append(f"drawdown {report.max_drawdown_pct:.1f}% exceeds {report.max_drawdown:.0f}% cap")
            if not report.profitable_days_passed:
                needed = report.min_profitable_days - report.profitable_days
                gaps.append(f"{needed} more profitable day{'s' if needed != 1 else ''}")
            if not report.avg_pnl_passed:
                gaps.append(f"avg P&L {report.avg_pnl_per_trade_cents:.0f}c below {report.min_avg_pnl_per_trade_cents}c")
            lines.append(f"{label}: NOT READY")
            lines.append(f"Need: {', '.join(gaps)}")

        return lines
