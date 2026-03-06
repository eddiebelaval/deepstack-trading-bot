"""
Graduation Gate — Go-Live Readiness Evaluation for DeepStack

Evaluates paper trading performance against defined thresholds to determine
readiness for live trading. Advisory only — Eddie flips the switch.

Thresholds (configurable via config.yaml):
  - Minimum closed paper trades (default: 50)
  - Minimum win rate (default: 45%)
  - Maximum drawdown as % of paper balance (default: 15%)
  - Profitable in N distinct market regimes (default: 2)

Queries trade_journal.db directly via SQLite. No schema migration required —
regime linkage uses timestamp JOIN against regime_history.
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import GraduationConfig

logger = logging.getLogger(__name__)


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


class GraduationGate:
    """
    Evaluates paper trading readiness for live transition.

    Opens its own read-only SQLite connection to trade_journal.db.
    All queries are SELECT-only — never modifies data.
    """

    def __init__(self, config: GraduationConfig, journal_db_path: str):
        self.config = config
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

    def evaluate(self) -> GraduationReport:
        """
        Run all 4 threshold checks against closed paper trades.

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
            logger.warning(f"GraduationGate: evaluation failed: {e}")
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
        # Normalize timestamps for comparison: trades use 'YYYY-MM-DD HH:MM:SS',
        # regime_history uses ISO 8601 'YYYY-MM-DDTHH:MM:SS.ffffff+00:00'.
        # SQLite datetime() normalizes both to comparable format.
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

    def get_progress_summary(self, report: Optional[GraduationReport] = None) -> str:
        """
        Human-readable progress string for Telegram/logs.

        Args:
            report: Pre-computed GraduationReport to avoid re-evaluation.
                    If None, calls evaluate() internally.

        Example:
            Graduation: 23/50 trades | 52% WR (need 45%) | 8% DD (max 15%) | 1/2 regimes
            Status: NOT READY — need 27 more trades, 1 more profitable regime
        """
        if report is None:
            report = self.evaluate()

        def _bar(current: int, target: int, width: int = 15) -> str:
            pct = min(current / target, 1.0) if target > 0 else 0
            filled = int(pct * width)
            return "[" + "|" * filled + "." * (width - filled) + "]"

        def _tag(passed: bool) -> str:
            return "PASSED" if passed else "---"

        num_profitable = len(report.profitable_regimes)

        lines = [
            "Graduation Progress",
            "-" * 35,
        ]

        # Trades: show progress bar when incomplete, tag when passed
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

        # Regimes: same pattern as trades
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
            lines.append("Status: READY — all thresholds passed")
            lines.append("Use /graduation go-live to review transition plan.")
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
            lines.append("Status: NOT READY")
            lines.append(f"Need: {', '.join(gaps)}")

        return "\n".join(lines)
