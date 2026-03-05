"""
Arena Storage — SQLite Persistence for Tournament Results

Stores tournament metadata, per-window per-strategy scores, aggregated
rankings, and promotion audit trail. Uses its own database file
(arena_results.db) to avoid lock contention with production trade_journal.db.

SQLite patterns borrowed from kalshi_trader/market_governor.py:
contextmanager + WAL mode for concurrent-safe access.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from arena.models import StrategyScore, TournamentResult

logger = logging.getLogger(__name__)

# Default database location: project root
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "arena_results.db"


@contextmanager
def _db_connection(
    db_path: Path, wal: bool = True
) -> Generator[sqlite3.Connection, None, None]:
    """Open a SQLite connection with WAL mode and timeout.

    Commits on success, rolls back on error, always closes.
    """
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


class ArenaDB:
    """SQLite persistence for arena tournament results."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self._init_tables()

    def _init_tables(self) -> None:
        """Create tables if they don't exist."""
        with _db_connection(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tournaments (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    data_source TEXT NOT NULL,
                    strategy_count INTEGER DEFAULT 0,
                    window_count INTEGER DEFAULT 0,
                    errors_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS window_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id TEXT NOT NULL,
                    window_id INTEGER NOT NULL,
                    strategy_name TEXT NOT NULL,
                    win_rate REAL DEFAULT 0,
                    sharpe_ratio REAL DEFAULT 0,
                    profit_factor REAL DEFAULT 0,
                    max_drawdown_pct REAL DEFAULT 0,
                    total_pnl_cents INTEGER DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    avg_pnl_cents REAL DEFAULT 0,
                    composite_score REAL DEFAULT 0,
                    rank INTEGER DEFAULT 0,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
                );

                CREATE TABLE IF NOT EXISTS strategy_rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    composite_score REAL DEFAULT 0,
                    rank INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    sharpe_ratio REAL DEFAULT 0,
                    profit_factor REAL DEFAULT 0,
                    max_drawdown_pct REAL DEFAULT 0,
                    total_pnl_cents INTEGER DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    avg_pnl_cents REAL DEFAULT 0,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
                );

                CREATE TABLE IF NOT EXISTS promotions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    composite_score REAL DEFAULT 0,
                    applied INTEGER DEFAULT 0,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
                );

                CREATE TABLE IF NOT EXISTS window_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id TEXT NOT NULL,
                    window_id INTEGER NOT NULL,
                    regime_label TEXT,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
                );

                CREATE TABLE IF NOT EXISTS regime_rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    composite_score REAL DEFAULT 0,
                    rank INTEGER DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
                );

                CREATE INDEX IF NOT EXISTS idx_window_scores_tournament
                    ON window_scores(tournament_id);
                CREATE INDEX IF NOT EXISTS idx_rankings_tournament
                    ON strategy_rankings(tournament_id);
                CREATE INDEX IF NOT EXISTS idx_rankings_strategy
                    ON strategy_rankings(strategy_name);
                CREATE INDEX IF NOT EXISTS idx_window_metadata_tournament
                    ON window_metadata(tournament_id);
                CREATE INDEX IF NOT EXISTS idx_regime_rankings_tournament
                    ON regime_rankings(tournament_id);
            """)

    def save_tournament(self, result: TournamentResult) -> None:
        """Save a complete tournament result."""
        with _db_connection(self.db_path) as conn:
            # Tournament metadata
            conn.execute(
                """INSERT INTO tournaments
                   (id, started_at, finished_at, data_source,
                    strategy_count, window_count, errors_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.tournament_id,
                    result.started_at.isoformat() if result.started_at else "",
                    result.finished_at.isoformat() if result.finished_at else "",
                    result.data_source,
                    result.total_strategies,
                    result.total_windows,
                    json.dumps(result.errors),
                ),
            )

            # Per-window scores
            for window_id, scores in result.window_scores.items():
                for score in scores:
                    conn.execute(
                        """INSERT INTO window_scores
                           (tournament_id, window_id, strategy_name,
                            win_rate, sharpe_ratio, profit_factor,
                            max_drawdown_pct, total_pnl_cents, total_trades,
                            avg_pnl_cents, composite_score, rank)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            result.tournament_id,
                            window_id,
                            score.strategy_name,
                            score.win_rate,
                            score.sharpe_ratio,
                            score.profit_factor,
                            score.max_drawdown_pct,
                            score.total_pnl_cents,
                            score.total_trades,
                            score.avg_pnl_cents,
                            score.composite_score,
                            score.rank,
                        ),
                    )

            # Aggregated rankings
            for score in result.rankings:
                conn.execute(
                    """INSERT INTO strategy_rankings
                       (tournament_id, strategy_name, composite_score, rank,
                        win_rate, sharpe_ratio, profit_factor,
                        max_drawdown_pct, total_pnl_cents, total_trades,
                        avg_pnl_cents)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result.tournament_id,
                        score.strategy_name,
                        score.composite_score,
                        score.rank,
                        score.win_rate,
                        score.sharpe_ratio,
                        score.profit_factor,
                        score.max_drawdown_pct,
                        score.total_pnl_cents,
                        score.total_trades,
                        score.avg_pnl_cents,
                    ),
                )

        logger.info(
            f"Saved tournament {result.tournament_id[:8]} "
            f"({result.total_strategies} strategies, "
            f"{result.total_windows} windows)"
        )

    def get_latest_tournament(self) -> Optional[Dict[str, Any]]:
        """Get the most recent tournament metadata."""
        with _db_connection(self.db_path) as conn:
            row = conn.execute(
                """SELECT * FROM tournaments
                   ORDER BY started_at DESC LIMIT 1"""
            ).fetchone()
            return dict(row) if row else None

    def get_strategy_history(
        self, strategy_name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get historical rankings for a specific strategy."""
        with _db_connection(self.db_path) as conn:
            rows = conn.execute(
                """SELECT r.*, t.started_at, t.data_source
                   FROM strategy_rankings r
                   JOIN tournaments t ON r.tournament_id = t.id
                   WHERE r.strategy_name = ?
                   ORDER BY t.started_at DESC
                   LIMIT ?""",
                (strategy_name, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_tournaments(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent tournaments."""
        with _db_connection(self.db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM tournaments
                   ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def save_regime_data(self, result: TournamentResult) -> None:
        """Save regime metadata and per-regime rankings from a seas tournament."""
        if not result.regime_scores:
            return

        with _db_connection(self.db_path) as conn:
            # Save per-regime aggregated rankings
            for regime, scores in result.regime_scores.items():
                for score in scores:
                    conn.execute(
                        """INSERT INTO regime_rankings
                           (tournament_id, regime, strategy_name,
                            composite_score, rank, total_trades)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            result.tournament_id,
                            regime,
                            score.strategy_name,
                            score.composite_score,
                            score.rank,
                            score.total_trades,
                        ),
                    )

        logger.info(
            f"Saved regime data for tournament {result.tournament_id[:8]} "
            f"({len(result.regime_scores)} regimes)"
        )

    def get_regime_scores(
        self, tournament_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get per-regime scores for a tournament.

        Returns:
            Dict of regime -> list of {strategy_name, composite_score, rank, ...}
        """
        with _db_connection(self.db_path) as conn:
            rows = conn.execute(
                """SELECT regime, strategy_name, composite_score, rank,
                          total_trades
                   FROM regime_rankings
                   WHERE tournament_id = ?
                   ORDER BY regime, rank""",
                (tournament_id,),
            ).fetchall()

        result: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            d = dict(row)
            regime = d.pop("regime")
            result.setdefault(regime, []).append(d)

        return result

    def get_fitness_matrix(
        self, tournament_id: str
    ) -> Dict[str, Dict[str, float]]:
        """Compute fitness matrix from stored regime scores.

        Returns:
            {strategy_name: {regime: fitness_0_to_1}}
        """
        regime_scores = self.get_regime_scores(tournament_id)
        matrix: Dict[str, Dict[str, float]] = {}

        for regime, scores in regime_scores.items():
            if not scores:
                continue
            max_score = max(s["composite_score"] for s in scores)
            if max_score <= 0:
                for s in scores:
                    matrix.setdefault(s["strategy_name"], {})[regime] = 0.0
                continue
            for s in scores:
                fitness = round(s["composite_score"] / max_score, 4)
                matrix.setdefault(s["strategy_name"], {})[regime] = fitness

        return matrix

    def save_promotions(
        self,
        tournament_id: str,
        candidates: list,
        applied: bool = False,
    ) -> None:
        """Record promotion decisions for audit trail."""
        now = datetime.now(timezone.utc).isoformat()
        with _db_connection(self.db_path) as conn:
            for c in candidates:
                conn.execute(
                    """INSERT INTO promotions
                       (tournament_id, timestamp, strategy_name,
                        recommendation, composite_score, applied)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        tournament_id,
                        now,
                        c.strategy_name,
                        c.recommendation,
                        c.avg_composite_score,
                        1 if applied else 0,
                    ),
                )
