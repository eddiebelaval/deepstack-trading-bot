"""
Fitness Writer — Bridge from Arena Scores to Governance Router

Writes arena-proven fitness scores into the production
strategy_regime_fitness table in trade_journal.db. This is the
same table that StrategyRouter (market_governor.py) reads to
blend priors with observed outcomes.

Safety:
    - Only writes when both --update-fitness and --apply flags are set
    - Backs up existing fitness rows before overwriting
    - Logs every change with tournament_id for audit trail
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


@contextmanager
def _db_connection(
    db_path: Path, wal: bool = True
) -> Generator[sqlite3.Connection, None, None]:
    """Open a SQLite connection with WAL mode and timeout."""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class FitnessWriter:
    """Write arena-proven fitness scores to the governance DB.

    Connects to the SAME database that market_governor.py's
    StrategyRouter reads from (trade_journal.db by default).
    """

    def __init__(self, db_path: str = "trade_journal.db"):
        self.db_path = Path(db_path).expanduser()
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create strategy_regime_fitness table if it doesn't exist."""
        with _db_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_regime_fitness (
                    strategy_name TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    fitness_score REAL DEFAULT 0.5,
                    trade_count INTEGER DEFAULT 0,
                    total_pnl_cents REAL DEFAULT 0.0,
                    last_updated TEXT,
                    PRIMARY KEY (strategy_name, regime)
                )
            """)

    def read_current(self) -> Dict[str, Dict[str, float]]:
        """Read current fitness scores from the governance DB.

        Returns:
            {strategy_name: {regime: fitness_score}}
        """
        result: Dict[str, Dict[str, float]] = {}
        try:
            with _db_connection(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT strategy_name, regime, fitness_score "
                    "FROM strategy_regime_fitness"
                ).fetchall()
            for row in rows:
                result.setdefault(row["strategy_name"], {})[
                    row["regime"]
                ] = row["fitness_score"]
        except Exception:
            pass  # Table may not exist yet
        return result

    def write_fitness(
        self,
        matrix: Dict[str, Dict[str, float]],
        tournament_id: str,
    ) -> int:
        """Write arena fitness scores to the governance DB.

        Uses UPSERT to update existing rows or insert new ones.
        Sets trade_count to a high value (100) so the Bayesian
        blending in StrategyRouter heavily weights arena data
        over the prior_strength (default 5).

        Args:
            matrix: {strategy_name: {regime: fitness_0_to_1}}
            tournament_id: For audit trail in last_updated field.

        Returns:
            Number of rows written.
        """
        now = datetime.now(timezone.utc).isoformat()
        audit_note = f"{now} (arena:{tournament_id[:8]})"
        written = 0

        with _db_connection(self.db_path) as conn:
            for strategy, regimes in matrix.items():
                for regime, fitness in regimes.items():
                    conn.execute(
                        """INSERT INTO strategy_regime_fitness
                           (strategy_name, regime, fitness_score,
                            trade_count, total_pnl_cents, last_updated)
                           VALUES (?, ?, ?, ?, 0.0, ?)
                           ON CONFLICT(strategy_name, regime) DO UPDATE SET
                           fitness_score = excluded.fitness_score,
                           trade_count = excluded.trade_count,
                           last_updated = excluded.last_updated""",
                        (strategy, regime, fitness, 100, audit_note),
                    )
                    written += 1

        logger.info(
            f"Wrote {written} fitness scores to {self.db_path} "
            f"(tournament {tournament_id[:8]})"
        )
        return written

    def backup_current(self) -> Dict[str, Dict[str, float]]:
        """Read and return current fitness for backup/diff purposes."""
        return self.read_current()

    @staticmethod
    def generate_diff(
        current: Dict[str, Dict[str, float]],
        proposed: Dict[str, Dict[str, float]],
    ) -> str:
        """Generate a human-readable diff between current and proposed fitness.

        Returns:
            Formatted string showing changes per strategy per regime.
        """
        lines = []
        divider = "=" * 72
        section = "-" * 72

        lines.append("")
        lines.append(divider)
        lines.append("  FITNESS UPDATE — PROPOSED CHANGES")
        lines.append(divider)

        # Collect all strategies and regimes
        all_strategies = sorted(
            set(list(current.keys()) + list(proposed.keys()))
        )
        all_regimes = sorted(set(
            r for d in list(current.values()) + list(proposed.values())
            for r in d
        ))

        if not all_regimes:
            lines.append("  No fitness data to compare.")
            lines.append(divider)
            return "\n".join(lines)

        # Header
        regime_cols = "".join(f"{r:<18}" for r in all_regimes)
        lines.append(f"  {'Strategy':<28}{regime_cols}")
        lines.append(section)

        for strategy in all_strategies:
            cur = current.get(strategy, {})
            prop = proposed.get(strategy, {})

            # Build per-regime cells
            cells = []
            has_change = False
            for regime in all_regimes:
                c = cur.get(regime)
                p = prop.get(regime)

                if c is not None and p is not None:
                    delta = p - c
                    if abs(delta) > 0.001:
                        has_change = True
                        arrow = "+" if delta > 0 else ""
                        cells.append(f"{c:.2f}->{p:.2f}")
                    else:
                        cells.append(f"{c:.2f}     ")
                elif p is not None:
                    has_change = True
                    cells.append(f"NEW {p:.2f}  ")
                elif c is not None:
                    cells.append(f"{c:.2f}     ")
                else:
                    cells.append("  ---      ")

            if has_change:
                regime_str = "".join(f"{c:<18}" for c in cells)
                lines.append(f"  {strategy:<28}{regime_str}")

        lines.append(section)

        # Summary
        total_changes = sum(
            1
            for s in all_strategies
            for r in all_regimes
            if proposed.get(s, {}).get(r) is not None
            and (
                current.get(s, {}).get(r) is None
                or abs(proposed[s][r] - current.get(s, {}).get(r, 0)) > 0.001
            )
        )
        lines.append(f"  {total_changes} fitness values would change")
        lines.append(divider)

        return "\n".join(lines)
