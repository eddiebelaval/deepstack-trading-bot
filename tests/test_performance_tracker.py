"""
Tests for PerformanceTracker — Bayesian Learning Loop.

Covers:
- Zero trades returns pure prior
- Single winning trade barely shifts blend
- 20 trades at 50/50 splits blend to midpoint
- All losses drives EV negative and triggers health warning
- Exponential decay: 30-day-old trade has weight ~0.5
- Prior persistence across tracker re-initialization
- Health status progression (healthy -> warning -> critical)
"""

import math
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from kalshi_trader.performance_tracker import PerformanceTracker, StrategyHealth


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_journal.db")


@pytest.fixture
def tracker(db_path):
    """Create a PerformanceTracker with test defaults."""
    # Create the trades table (normally done by TradeJournal)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            market_ticker TEXT,
            side TEXT,
            action TEXT,
            contracts INTEGER,
            entry_price_cents INTEGER,
            fill_price_cents INTEGER,
            exit_price_cents INTEGER,
            pnl_cents INTEGER,
            order_id TEXT,
            exit_order_id TEXT,
            status TEXT DEFAULT 'pending',
            reasoning TEXT,
            exit_reason TEXT,
            strategy TEXT DEFAULT 'mean_reversion',
            session_date DATE,
            metadata TEXT
        )
    """)
    conn.commit()
    conn.close()

    t = PerformanceTracker(
        db_path=db_path,
        prior_strength=20,
        decay_half_life_days=30.0,
    )
    yield t
    t.close()


@pytest.fixture
def tracker_with_prior(tracker):
    """Tracker with a mean_reversion prior registered."""
    tracker.register_prior("mean_reversion", {
        "win_rate": 0.60,
        "avg_win_cents": 8.0,
        "avg_loss_cents": 5.0,
    })
    return tracker


def _insert_trade(db_path, strategy, pnl_cents, age_days=0):
    """Insert a fake closed trade into the trades table."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Ensure trades table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            market_ticker TEXT,
            side TEXT,
            action TEXT,
            contracts INTEGER,
            entry_price_cents INTEGER,
            fill_price_cents INTEGER,
            exit_price_cents INTEGER,
            pnl_cents INTEGER,
            order_id TEXT,
            exit_order_id TEXT,
            status TEXT DEFAULT 'pending',
            reasoning TEXT,
            exit_reason TEXT,
            strategy TEXT DEFAULT 'mean_reversion',
            session_date DATE,
            metadata TEXT
        )
    """)

    import uuid
    trade_id = str(uuid.uuid4())[:8]
    created_at = (datetime.now() - timedelta(days=age_days)).isoformat()

    conn.execute(
        """
        INSERT INTO trades (id, market_ticker, side, action, contracts,
            entry_price_cents, pnl_cents, status, strategy, created_at)
        VALUES (?, 'TEST-MKT', 'yes', 'buy', 1, 50, ?, 'closed', ?, ?)
        """,
        (trade_id, pnl_cents, strategy, created_at),
    )
    conn.commit()
    conn.close()


class TestZeroTrades:
    """When no trades exist, should return pure prior."""

    def test_returns_prior_win_rate(self, tracker_with_prior):
        stats = tracker_with_prior.get_blended_stats("mean_reversion")
        assert stats["win_rate"] == 0.60

    def test_returns_prior_avg_win(self, tracker_with_prior):
        stats = tracker_with_prior.get_blended_stats("mean_reversion")
        assert stats["avg_win_cents"] == 8.0

    def test_returns_prior_avg_loss(self, tracker_with_prior):
        stats = tracker_with_prior.get_blended_stats("mean_reversion")
        assert stats["avg_loss_cents"] == 5.0


class TestSingleWinningTrade:
    """One winning trade should barely shift the blend (~2.4%)."""

    def test_win_rate_shifts_slightly(self, tracker_with_prior, db_path):
        _insert_trade(db_path, "mean_reversion", pnl_cents=10)
        stats = tracker_with_prior.get_blended_stats("mean_reversion")
        # Prior: 0.60, Observed: 1.0 (one win), k=20, n~1
        # Blended ~ (20 * 0.60 + 1 * 1.0) / 21 ~ 0.619
        assert 0.61 < stats["win_rate"] < 0.63

    def test_avg_win_shifts_slightly(self, tracker_with_prior, db_path):
        _insert_trade(db_path, "mean_reversion", pnl_cents=10)
        stats = tracker_with_prior.get_blended_stats("mean_reversion")
        # Prior avg_win: 8.0, Observed: 10, k=20, n~1
        # Blended ~ (20*8 + 1*10) / 21 ~ 8.095
        assert 8.0 < stats["avg_win_cents"] < 8.2


class TestBalancedTrades:
    """20 trades at 50/50 should blend prior and observed equally."""

    def test_twenty_trades_half_wins(self, tracker_with_prior, db_path):
        # Insert 10 wins and 10 losses (all recent, high weight)
        for _ in range(10):
            _insert_trade(db_path, "mean_reversion", pnl_cents=8)
        for _ in range(10):
            _insert_trade(db_path, "mean_reversion", pnl_cents=-5)

        stats = tracker_with_prior.get_blended_stats("mean_reversion")
        # Observed win rate: 0.50, Prior: 0.60, k=20, n~20
        # Blended ~ (20*0.60 + 20*0.50) / 40 ~ 0.55
        assert 0.54 < stats["win_rate"] < 0.56


class TestAllLosses:
    """All losses should drive EV negative and trigger health warning."""

    def test_negative_ev_triggers_warning(self, tracker_with_prior, db_path):
        # Insert enough losing trades to overwhelm prior
        for _ in range(30):
            _insert_trade(db_path, "mean_reversion", pnl_cents=-5)

        health = tracker_with_prior.evaluate_health("mean_reversion")
        assert health.blended_ev_cents < 0
        assert health.health_status in ("warning", "critical")

    def test_blended_win_rate_drops(self, tracker_with_prior, db_path):
        for _ in range(30):
            _insert_trade(db_path, "mean_reversion", pnl_cents=-5)

        stats = tracker_with_prior.get_blended_stats("mean_reversion")
        # Observed: 0% wins, Prior: 60%, k=20, n~30
        # Blended ~ (20*0.60 + 30*0.0) / 50 ~ 0.24
        assert stats["win_rate"] < 0.30


class TestExponentialDecay:
    """30-day-old trade should have weight ~0.5."""

    def test_old_trade_has_half_weight(self, tracker_with_prior, db_path):
        # One recent win, one 30-day-old loss
        _insert_trade(db_path, "mean_reversion", pnl_cents=8, age_days=0)
        _insert_trade(db_path, "mean_reversion", pnl_cents=-5, age_days=30)

        stats = tracker_with_prior.get_blended_stats("mean_reversion")
        # Recent win: weight ~1.0, Old loss: weight ~0.5
        # Effective n ~ 1.5, weighted_wins ~ 1.0
        # Observed win_rate ~ 1.0/1.5 ~ 0.667
        # Blended ~ (20*0.60 + 1.5*0.667) / 21.5 ~ 0.604
        assert stats["win_rate"] > 0.60  # Recent win pulls up

    def test_very_old_trade_nearly_zero_weight(self, tracker_with_prior, db_path):
        # One recent trade, one 180-day-old trade (6 half-lives = 1/64 weight)
        _insert_trade(db_path, "mean_reversion", pnl_cents=8, age_days=0)
        _insert_trade(db_path, "mean_reversion", pnl_cents=-5, age_days=180)

        n = tracker_with_prior._get_effective_trade_count("mean_reversion")
        # Recent: ~1.0, 180-day: ~0.015
        assert 1.0 < n < 1.1


class TestPriorPersistence:
    """Priors should persist across tracker re-initialization."""

    def test_prior_survives_reinit(self, db_path):
        # First tracker registers prior
        t1 = PerformanceTracker(db_path=db_path)
        t1.register_prior("mean_reversion", {
            "win_rate": 0.60,
            "avg_win_cents": 8.0,
            "avg_loss_cents": 5.0,
        })
        t1.close()

        # Second tracker should find it
        t2 = PerformanceTracker(db_path=db_path)
        prior = t2.get_prior("mean_reversion")
        t2.close()

        assert prior is not None
        assert prior.win_rate == 0.60
        assert prior.avg_win_cents == 8.0

    def test_register_replaces_stale_prior(self, db_path):
        """INSERT OR REPLACE means re-registering updates values (Round 2 P0 fix)."""
        t1 = PerformanceTracker(db_path=db_path)
        t1.register_prior("test_strat", {
            "win_rate": 0.60,
            "avg_win_cents": 8.0,
            "avg_loss_cents": 5.0,
        })

        # Update with new values
        t1.register_prior("test_strat", {
            "win_rate": 0.99,
            "avg_win_cents": 100.0,
            "avg_loss_cents": 1.0,
        })

        prior = t1.get_prior("test_strat")
        t1.close()

        # Updated values should persist (INSERT OR REPLACE)
        assert prior.win_rate == 0.99


class TestHealthProgression:
    """Health should progress from healthy -> warning -> critical."""

    def test_healthy_with_positive_ev(self, tracker_with_prior, db_path):
        # All wins
        for _ in range(5):
            _insert_trade(db_path, "mean_reversion", pnl_cents=8)

        health = tracker_with_prior.evaluate_health("mean_reversion")
        assert health.health_status == "healthy"
        assert health.blended_ev_cents > 0

    def test_warning_escalates_to_critical(self, tracker_with_prior, db_path):
        # Insert enough losses with grace_period_trades
        tracker_with_prior.grace_period_trades = 5
        for _ in range(20):
            _insert_trade(db_path, "mean_reversion", pnl_cents=-10)

        # Evaluate multiple times to accumulate warnings
        h1 = tracker_with_prior.evaluate_health("mean_reversion")
        assert h1.health_status in ("warning", "critical")

        h2 = tracker_with_prior.evaluate_health("mean_reversion")
        h3 = tracker_with_prior.evaluate_health("mean_reversion")

        # By third evaluation, should be critical (3 consecutive warnings)
        assert h3.health_status == "critical"
        assert h3.consecutive_warnings >= 3

    def test_recovery_resets_warnings(self, tracker_with_prior, db_path):
        # Start with losses to get warning
        for _ in range(20):
            _insert_trade(db_path, "mean_reversion", pnl_cents=-10)

        h1 = tracker_with_prior.evaluate_health("mean_reversion")
        assert h1.consecutive_warnings > 0

        # Now add many wins to flip EV positive
        for _ in range(50):
            _insert_trade(db_path, "mean_reversion", pnl_cents=20)

        h2 = tracker_with_prior.evaluate_health("mean_reversion")
        assert h2.consecutive_warnings == 0
        assert h2.health_status == "healthy"


class TestEvaluateAll:
    """evaluate_all should return health for all registered strategies."""

    def test_returns_all_registered(self, tracker):
        tracker.register_prior("strat_a", {
            "win_rate": 0.60,
            "avg_win_cents": 8.0,
            "avg_loss_cents": 5.0,
        })
        tracker.register_prior("strat_b", {
            "win_rate": 0.55,
            "avg_win_cents": 10.0,
            "avg_loss_cents": 6.0,
        })

        results = tracker.evaluate_all()
        assert "strat_a" in results
        assert "strat_b" in results
        assert isinstance(results["strat_a"], StrategyHealth)


class TestNoTracker:
    """Without a prior, should return conservative defaults."""

    def test_missing_prior_returns_defaults(self, tracker):
        stats = tracker.get_blended_stats("nonexistent_strategy")
        assert stats["win_rate"] == 0.55
        assert stats["avg_win_cents"] == 8.0
        assert stats["avg_loss_cents"] == 5.0


class TestConfidence:
    """Confidence should increase with more trades."""

    def test_zero_trades_zero_confidence(self, tracker_with_prior):
        health = tracker_with_prior.evaluate_health("mean_reversion")
        assert health.confidence == 0.0

    def test_twenty_trades_fifty_pct_confidence(self, tracker_with_prior, db_path):
        for _ in range(20):
            _insert_trade(db_path, "mean_reversion", pnl_cents=8)

        health = tracker_with_prior.evaluate_health("mean_reversion")
        # n~20, k=20, confidence = 20/(20+20) = 0.5
        assert 0.45 < health.confidence < 0.55
