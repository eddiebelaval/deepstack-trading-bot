"""
Performance Tracker — Bayesian Learning Loop for Trading Strategies

Closes the feedback loop between trade outcomes and position sizing.
Blends hardcoded strategy priors with actual trade performance using
Bayesian updating with exponential time-decay.

Math:
    decay_weight = exp(-ln(2) * age_days / half_life_days)
    effective_n = sum(weights) for all closed trades
    blended = (k * prior + n * observed) / (k + n)
    confidence = n / (n + k)

Tables (same trade_journal.db):
    - strategy_priors: Registered priors from hardcoded stats
    - strategy_health: Latest blended stats and health status
"""

import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class StrategyPrior:
    """Hardcoded strategy assumptions registered at startup."""

    strategy_name: str
    win_rate: float
    avg_win_cents: float
    avg_loss_cents: float
    prior_strength: int = 20


@dataclass
class StrategyHealth:
    """Blended stats + health assessment for a strategy."""

    strategy_name: str
    blended_win_rate: float
    blended_avg_win_cents: float
    blended_avg_loss_cents: float
    blended_ev_cents: float
    observed_trade_count: int
    effective_trade_count: float
    confidence: float
    health_status: str  # "healthy", "warning", "critical"
    consecutive_warnings: int


class PerformanceTracker:
    """
    Bayesian performance tracker that blends priors with observed trades.

    Uses the same SQLite database as TradeJournal (WAL mode handles
    concurrent reads). Creates two new tables: strategy_priors and
    strategy_health.

    Usage:
        tracker = PerformanceTracker("./trade_journal.db")
        tracker.register_prior("mean_reversion", {
            "win_rate": 0.60,
            "avg_win_cents": 8.0,
            "avg_loss_cents": 5.0,
        })
        stats = tracker.get_blended_stats("mean_reversion")
        health = tracker.evaluate_health("mean_reversion")
    """

    def __init__(
        self,
        db_path: str,
        prior_strength: int = 20,
        decay_half_life_days: float = 30.0,
        auto_disable: bool = False,
        grace_period_trades: int = 10,
    ):
        self.db_path = Path(db_path).expanduser()
        self.prior_strength = prior_strength
        self.decay_half_life_days = decay_half_life_days
        self.auto_disable = auto_disable
        self.grace_period_trades = grace_period_trades

        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

        logger.info(
            f"PerformanceTracker initialized | k={prior_strength}, "
            f"half_life={decay_half_life_days}d, auto_disable={auto_disable}"
        )

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategy_priors (
                strategy_name TEXT PRIMARY KEY,
                win_rate REAL NOT NULL,
                avg_win_cents REAL NOT NULL,
                avg_loss_cents REAL NOT NULL,
                prior_strength INTEGER DEFAULT 20,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategy_health (
                strategy_name TEXT PRIMARY KEY,
                blended_win_rate REAL,
                blended_avg_win_cents REAL,
                blended_avg_loss_cents REAL,
                blended_ev_cents REAL,
                observed_trade_count INTEGER DEFAULT 0,
                effective_trade_count REAL DEFAULT 0.0,
                confidence REAL DEFAULT 0.0,
                health_status TEXT DEFAULT 'healthy',
                consecutive_warnings INTEGER DEFAULT 0,
                last_evaluated TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learned_params (
                strategy_name TEXT PRIMARY KEY,
                take_profit_cents INTEGER,
                stop_loss_cents INTEGER,
                sample_size INTEGER DEFAULT 0,
                last_computed TIMESTAMP
            )
        """)

        conn.commit()

    def register_prior(self, strategy_name: str, stats: Dict[str, float]) -> None:
        """
        Register a strategy's hardcoded prior stats.

        Uses INSERT OR IGNORE so priors persist across restarts
        without overwriting manually tuned values.
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR IGNORE INTO strategy_priors
                (strategy_name, win_rate, avg_win_cents, avg_loss_cents, prior_strength)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                strategy_name,
                stats["win_rate"],
                stats["avg_win_cents"],
                stats["avg_loss_cents"],
                self.prior_strength,
            ),
        )
        conn.commit()
        logger.debug(f"Prior registered for {strategy_name}: {stats}")

    def get_prior(self, strategy_name: str) -> Optional[StrategyPrior]:
        """Load a strategy's prior from the database."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM strategy_priors WHERE strategy_name = ?",
            (strategy_name,),
        ).fetchone()

        if not row:
            return None

        return StrategyPrior(
            strategy_name=row["strategy_name"],
            win_rate=row["win_rate"],
            avg_win_cents=row["avg_win_cents"],
            avg_loss_cents=row["avg_loss_cents"],
            prior_strength=row["prior_strength"],
        )

    def get_blended_stats(self, strategy_name: str) -> Dict[str, float]:
        """
        THE KEY METHOD. Returns Kelly-compatible dict with blended values.

        Blends registered prior with actual trade outcomes, weighting
        recent trades more heavily via exponential decay.

        If no prior is registered or no trades exist, falls back gracefully.
        """
        prior = self.get_prior(strategy_name)
        if not prior:
            logger.warning(f"No prior for {strategy_name}, returning conservative defaults")
            return {
                "win_rate": 0.55,
                "avg_win_cents": 8.0,
                "avg_loss_cents": 5.0,
            }

        # Query closed trades for this strategy
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT pnl_cents, created_at
                FROM trades
                WHERE strategy = ? AND status = 'closed' AND pnl_cents IS NOT NULL
                ORDER BY created_at DESC
                """,
                (strategy_name,),
            ).fetchall()
        except sqlite3.OperationalError:
            # trades table doesn't exist yet (TradeJournal not initialized)
            rows = []

        if not rows:
            # No trades yet — return pure prior
            return {
                "win_rate": prior.win_rate,
                "avg_win_cents": prior.avg_win_cents,
                "avg_loss_cents": prior.avg_loss_cents,
            }

        # Calculate decay-weighted observed stats
        now = datetime.now()
        decay_ln2 = math.log(2)

        total_weight = 0.0
        weighted_wins = 0.0
        weighted_win_sum = 0.0
        weighted_loss_sum = 0.0
        win_weight_sum = 0.0
        loss_weight_sum = 0.0

        for row in rows:
            pnl = row["pnl_cents"]
            created = row["created_at"]

            # Parse timestamp
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created)
                except ValueError:
                    created = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")

            age_days = max((now - created).total_seconds() / 86400, 0)
            weight = math.exp(-decay_ln2 * age_days / self.decay_half_life_days)

            total_weight += weight

            if pnl > 0:
                weighted_wins += weight
                weighted_win_sum += weight * pnl
                win_weight_sum += weight
            elif pnl < 0:
                weighted_loss_sum += weight * abs(pnl)
                loss_weight_sum += weight
            # pnl == 0 trades count toward total_weight but are neither win nor loss

        # Observed stats (from decay-weighted trades)
        observed_win_rate = weighted_wins / total_weight if total_weight > 0 else 0.5
        observed_avg_win = weighted_win_sum / win_weight_sum if win_weight_sum > 0 else prior.avg_win_cents
        observed_avg_loss = weighted_loss_sum / loss_weight_sum if loss_weight_sum > 0 else prior.avg_loss_cents

        # Bayesian blend: blended = (k * prior + n * observed) / (k + n)
        k = prior.prior_strength
        n = total_weight  # effective trade count

        blended_win_rate = (k * prior.win_rate + n * observed_win_rate) / (k + n)
        blended_avg_win = (k * prior.avg_win_cents + n * observed_avg_win) / (k + n)
        blended_avg_loss = (k * prior.avg_loss_cents + n * observed_avg_loss) / (k + n)

        return {
            "win_rate": blended_win_rate,
            "avg_win_cents": blended_avg_win,
            "avg_loss_cents": blended_avg_loss,
        }

    def evaluate_health(self, strategy_name: str) -> StrategyHealth:
        """
        Evaluate strategy health based on blended stats.

        Health status:
        - "healthy": positive blended EV
        - "warning": negative blended EV or significant underperformance
        - "critical": sustained warnings beyond grace period
        """
        stats = self.get_blended_stats(strategy_name)
        prior = self.get_prior(strategy_name)

        win_rate = stats["win_rate"]
        avg_win = stats["avg_win_cents"]
        avg_loss = stats["avg_loss_cents"]

        # Calculate blended EV
        ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Count actual trades and effective weight
        conn = self._get_conn()
        try:
            count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades WHERE strategy = ? AND status = 'closed'",
                (strategy_name,),
            ).fetchone()
            observed_count = count_row["cnt"] if count_row else 0
        except sqlite3.OperationalError:
            observed_count = 0

        # Calculate effective trade count (sum of decay weights)
        k = prior.prior_strength if prior else self.prior_strength
        n = self._get_effective_trade_count(strategy_name)
        confidence = n / (n + k) if (n + k) > 0 else 0.0

        # Get current consecutive warnings
        health_row = conn.execute(
            "SELECT consecutive_warnings FROM strategy_health WHERE strategy_name = ?",
            (strategy_name,),
        ).fetchone()
        prev_warnings = health_row["consecutive_warnings"] if health_row else 0

        # Determine health status
        health_status = "healthy"
        consecutive_warnings = 0

        if ev < 0 and confidence > 0.2:
            health_status = "warning"
            consecutive_warnings = prev_warnings + 1

            if consecutive_warnings >= 3 and observed_count >= self.grace_period_trades:
                health_status = "critical"
        else:
            consecutive_warnings = 0

        # Persist health status
        health = StrategyHealth(
            strategy_name=strategy_name,
            blended_win_rate=win_rate,
            blended_avg_win_cents=avg_win,
            blended_avg_loss_cents=avg_loss,
            blended_ev_cents=ev,
            observed_trade_count=observed_count,
            effective_trade_count=n,
            confidence=confidence,
            health_status=health_status,
            consecutive_warnings=consecutive_warnings,
        )

        self._save_health(health)

        if health_status != "healthy":
            logger.warning(
                f"Strategy {strategy_name} health: {health_status} | "
                f"EV={ev:.2f}c, confidence={confidence:.1%}, "
                f"warnings={consecutive_warnings}"
            )

        return health

    def evaluate_all(self) -> Dict[str, StrategyHealth]:
        """Evaluate health for all registered strategies."""
        conn = self._get_conn()
        rows = conn.execute("SELECT strategy_name FROM strategy_priors").fetchall()
        return {row["strategy_name"]: self.evaluate_health(row["strategy_name"]) for row in rows}

    def _get_effective_trade_count(self, strategy_name: str) -> float:
        """Calculate sum of decay weights for a strategy's closed trades."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT created_at FROM trades
                WHERE strategy = ? AND status = 'closed' AND pnl_cents IS NOT NULL
                """,
                (strategy_name,),
            ).fetchall()
        except sqlite3.OperationalError:
            return 0.0

        if not rows:
            return 0.0

        now = datetime.now()
        decay_ln2 = math.log(2)
        total = 0.0

        for row in rows:
            created = row["created_at"]
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created)
                except ValueError:
                    created = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")

            age_days = max((now - created).total_seconds() / 86400, 0)
            total += math.exp(-decay_ln2 * age_days / self.decay_half_life_days)

        return total

    def _save_health(self, health: StrategyHealth) -> None:
        """Persist health assessment to strategy_health table."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO strategy_health (
                strategy_name, blended_win_rate, blended_avg_win_cents,
                blended_avg_loss_cents, blended_ev_cents, observed_trade_count,
                effective_trade_count, confidence, health_status,
                consecutive_warnings, last_evaluated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                health.strategy_name,
                health.blended_win_rate,
                health.blended_avg_win_cents,
                health.blended_avg_loss_cents,
                health.blended_ev_cents,
                health.observed_trade_count,
                health.effective_trade_count,
                health.confidence,
                health.health_status,
                health.consecutive_warnings,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()

    # ── Adaptive Thresholds ──────────────────────────────────────────

    def get_adaptive_params(self, strategy_name: str) -> Optional[Dict[str, float]]:
        """
        Compute adaptive take_profit and stop_loss from closed trade distribution.

        Returns adjusted params only when enough data exists (>= 5 closed trades).
        Uses percentile-based approach:
          - take_profit = 75th percentile of winning P&Ls (capture realistic wins)
          - stop_loss = 75th percentile of losing P&Ls (allow realistic drawdowns)

        Falls back to None if insufficient data, letting caller use config defaults.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT pnl_cents, created_at
                FROM trades
                WHERE strategy = ? AND status = 'closed' AND pnl_cents IS NOT NULL
                ORDER BY pnl_cents
                """,
                (strategy_name,),
            ).fetchall()
        except sqlite3.OperationalError:
            return None

        if len(rows) < 5:
            return None

        wins = [r["pnl_cents"] for r in rows if r["pnl_cents"] > 0]
        losses = [abs(r["pnl_cents"]) for r in rows if r["pnl_cents"] < 0]

        if not wins or not losses:
            return None

        wins.sort()
        losses.sort()

        def percentile(data: list, pct: float) -> float:
            idx = (len(data) - 1) * pct
            lower = int(idx)
            upper = min(lower + 1, len(data) - 1)
            weight = idx - lower
            return data[lower] * (1 - weight) + data[upper] * weight

        # 75th percentile: capture most realistic targets, not outliers
        adaptive_tp = max(2, round(percentile(wins, 0.75)))
        adaptive_sl = max(2, round(percentile(losses, 0.75)))

        # Persist for dashboard visibility
        conn.execute(
            """
            INSERT OR REPLACE INTO learned_params
                (strategy_name, take_profit_cents, stop_loss_cents,
                 sample_size, last_computed)
            VALUES (?, ?, ?, ?, ?)
            """,
            (strategy_name, adaptive_tp, adaptive_sl,
             len(rows), datetime.now().isoformat()),
        )
        conn.commit()

        logger.info(
            f"Adaptive params for {strategy_name}: "
            f"TP={adaptive_tp}c, SL={adaptive_sl}c "
            f"(from {len(wins)} wins, {len(losses)} losses)"
        )

        return {
            "take_profit_cents": adaptive_tp,
            "stop_loss_cents": adaptive_sl,
            "sample_wins": len(wins),
            "sample_losses": len(losses),
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
