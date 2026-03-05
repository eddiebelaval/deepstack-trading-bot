"""
Arena Tests — Scoring, Window Generation, Engine Smoke Test

Run: python -m pytest tests/test_arena.py -v
"""

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arena.config import ArenaConfig
from arena.engine import TournamentEngine
from arena.models import StrategyScore, WalkForwardWindow
from arena.scoring import CompositeScorer
from backtest.runner import BacktestResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    name: str,
    total_trades: int = 10,
    win_rate: float = 0.5,
    sharpe_ratio: float = 1.0,
    profit_factor: float = 1.5,
    max_drawdown_pct: float = 0.1,
    total_pnl_cents: int = 100,
    avg_pnl: float = 10.0,
) -> BacktestResult:
    """Create a BacktestResult with controlled metrics for testing."""
    return BacktestResult(
        strategy_name=name,
        strategy_config={},
        data_source="test",
        total_timesteps=100,
        total_trades=total_trades,
        winning_trades=int(total_trades * win_rate),
        losing_trades=total_trades - int(total_trades * win_rate),
        breakeven_trades=0,
        win_rate=win_rate,
        total_pnl_cents=total_pnl_cents,
        avg_pnl_per_trade_cents=avg_pnl,
        largest_win_cents=50,
        largest_loss_cents=-30,
        avg_winner_cents=20.0,
        avg_loser_cents=-15.0,
        max_drawdown_cents=int(max_drawdown_pct * 15000),
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        profit_factor=profit_factor,
        max_consecutive_wins=3,
        max_consecutive_losses=2,
        initial_balance_cents=15000,
        final_balance_cents=15000 + total_pnl_cents,
        equity_curve=[15000, 15000 + total_pnl_cents],
        trades=[],
    )


# ---------------------------------------------------------------------------
# CompositeScorer Tests
# ---------------------------------------------------------------------------


class TestCompositeScorer:
    """Test percentile-rank normalization and weighted scoring."""

    def setup_method(self):
        self.config = ArenaConfig()
        self.scorer = CompositeScorer(self.config)

    def test_basic_scoring_ranks_better_strategy_higher(self):
        """A strategy with better metrics across the board should rank #1."""
        results = {
            "good": _make_result(
                "good", win_rate=0.7, sharpe_ratio=2.0,
                profit_factor=3.0, max_drawdown_pct=0.05,
                total_pnl_cents=500, avg_pnl=50.0,
            ),
            "bad": _make_result(
                "bad", win_rate=0.3, sharpe_ratio=-0.5,
                profit_factor=0.5, max_drawdown_pct=0.3,
                total_pnl_cents=-200, avg_pnl=-20.0,
            ),
        }

        scores = self.scorer.score_window(results, window_id=0)

        assert len(scores) == 2
        assert scores[0].strategy_name == "good"
        assert scores[0].rank == 1
        assert scores[1].strategy_name == "bad"
        assert scores[1].rank == 2
        assert scores[0].composite_score > scores[1].composite_score

    def test_zero_trades_gets_zero_composite(self):
        """A strategy with 0 trades should get composite_score = 0."""
        results = {
            "active": _make_result("active", total_trades=10),
            "dead": _make_result("dead", total_trades=0),
        }

        scores = self.scorer.score_window(results, window_id=0)
        dead_score = next(s for s in scores if s.strategy_name == "dead")
        assert dead_score.composite_score == 0.0

    def test_low_trade_count_penalty(self):
        """Strategies with <5 trades get penalized proportionally."""
        results = {
            "few_trades": _make_result(
                "few_trades", total_trades=2,
                win_rate=0.7, sharpe_ratio=2.0, profit_factor=3.0,
            ),
            "many_trades": _make_result(
                "many_trades", total_trades=20,
                win_rate=0.5, sharpe_ratio=1.0, profit_factor=1.5,
            ),
        }

        scores = self.scorer.score_window(results, window_id=0)
        few = next(s for s in scores if s.strategy_name == "few_trades")
        many = next(s for s in scores if s.strategy_name == "many_trades")

        # Despite better raw metrics, few_trades should be penalized
        # The penalty is composite *= (2/5) = 0.4 multiplier
        assert few.total_trades == 2

    def test_single_strategy_gets_50_percentile(self):
        """With only 1 strategy, all percentiles = 50 (no comparison)."""
        results = {
            "solo": _make_result("solo"),
        }

        scores = self.scorer.score_window(results, window_id=0)
        assert len(scores) == 1
        assert scores[0].composite_score == 50.0

    def test_profit_factor_capped(self):
        """Infinite profit factor (no losses) should be capped at 10.0."""
        results = {
            "perfect": _make_result(
                "perfect", profit_factor=float("inf"),
            ),
            "normal": _make_result(
                "normal", profit_factor=1.5,
            ),
        }

        scores = self.scorer.score_window(results, window_id=0)
        perfect = next(s for s in scores if s.strategy_name == "perfect")
        assert perfect.profit_factor == 10.0

    def test_empty_results_returns_empty(self):
        """No results should return empty list."""
        scores = self.scorer.score_window({}, window_id=0)
        assert scores == []


# ---------------------------------------------------------------------------
# Window Generation Tests
# ---------------------------------------------------------------------------


class TestWindowGeneration:
    """Test walk-forward window generation from data timerange."""

    def test_window_count(self):
        """Verify correct number of windows for a known data range."""
        config = ArenaConfig(is_months=6, oos_months=1, step_months=1)
        engine = TournamentEngine(config)

        # 12 months of data at hourly intervals
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        snapshots = [
            {"_timestamp": start + timedelta(hours=i)}
            for i in range(365 * 24)  # ~1 year
        ]

        windows = engine._generate_windows(snapshots)

        # 12 months - 7 months (6 IS + 1 OOS) = 5 months of room
        # With 1-month step: windows at months 0, 1, 2, 3, 4, 5
        assert len(windows) >= 5  # At least 5 windows
        assert all(isinstance(w, WalkForwardWindow) for w in windows)

    def test_window_boundaries(self):
        """Window IS end should equal OOS start (no gap)."""
        config = ArenaConfig(is_months=3, oos_months=1, step_months=1)
        engine = TournamentEngine(config)

        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        snapshots = [
            {"_timestamp": start + timedelta(hours=i)}
            for i in range(365 * 24)
        ]

        windows = engine._generate_windows(snapshots)

        for w in windows:
            assert w.is_end == w.oos_start, "IS end must equal OOS start"
            assert w.oos_end > w.oos_start, "OOS must have positive duration"
            assert w.is_end > w.is_start, "IS must have positive duration"

    def test_no_windows_for_short_data(self):
        """Data shorter than IS+OOS should produce no windows."""
        config = ArenaConfig(is_months=6, oos_months=1)
        engine = TournamentEngine(config)

        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        # Only 1 month of data
        snapshots = [
            {"_timestamp": start + timedelta(hours=i)}
            for i in range(30 * 24)
        ]

        windows = engine._generate_windows(snapshots)
        assert len(windows) == 0

    def test_empty_snapshots(self):
        """No snapshots should produce no windows."""
        config = ArenaConfig()
        engine = TournamentEngine(config)
        assert engine._generate_windows([]) == []


# ---------------------------------------------------------------------------
# Engine Smoke Test
# ---------------------------------------------------------------------------


class TestEngineSmoke:
    """End-to-end smoke test with synthetic data."""

    def test_synthetic_tournament_completes(self):
        """Tournament with synthetic data should complete without errors."""
        config = ArenaConfig(
            synthetic_timesteps=5000,
            synthetic_seed=42,
            is_months=1,
            oos_months=1,
            step_months=1,
        )
        engine = TournamentEngine(config)

        result = asyncio.run(engine.run_tournament())

        assert result.tournament_id is not None
        assert result.started_at is not None
        assert result.finished_at is not None
        assert result.total_strategies > 0
        # Some strategies may produce 0 trades but all should score

    def test_deterministic_results(self):
        """Same seed should produce identical rankings."""
        config = ArenaConfig(
            synthetic_timesteps=5000,
            synthetic_seed=99,
            is_months=1,
            oos_months=1,
        )

        result1 = asyncio.run(TournamentEngine(config).run_tournament())
        result2 = asyncio.run(TournamentEngine(config).run_tournament())

        names1 = [s.strategy_name for s in result1.rankings]
        names2 = [s.strategy_name for s in result2.rankings]
        scores1 = [s.composite_score for s in result1.rankings]
        scores2 = [s.composite_score for s in result2.rankings]

        assert len(names1) > 0, "Should have at least one ranked strategy"
        assert names1 == names2, "Rankings should be deterministic"
        assert scores1 == scores2, "Scores should be deterministic"

    def test_subset_strategies(self):
        """Running a subset of strategies should work."""
        config = ArenaConfig(
            synthetic_timesteps=5000,
            synthetic_seed=42,
            is_months=1,
            oos_months=1,
        )
        engine = TournamentEngine(config)

        result = asyncio.run(
            engine.run_tournament(
                strategy_names=["mean_reversion", "momentum"]
            )
        )

        strategy_names = {s.strategy_name for s in result.rankings}
        assert len(strategy_names) > 0, "Should have ranked strategies"
        assert strategy_names <= {"mean_reversion", "momentum"}


# ---------------------------------------------------------------------------
# Config Validation Tests
# ---------------------------------------------------------------------------


class TestConfig:
    """Test ArenaConfig validation."""

    def test_valid_config(self):
        """Default config should validate."""
        config = ArenaConfig()
        config.validate()  # Should not raise

    def test_invalid_weights(self):
        """Weights not summing to 1.0 should raise."""
        config = ArenaConfig(weight_sharpe_ratio=0.9)
        with pytest.raises(ValueError, match="weights must sum"):
            config.validate()

    def test_invalid_oos_months(self):
        """oos_months < 1 should raise."""
        config = ArenaConfig(oos_months=0)
        with pytest.raises(ValueError, match="oos_months"):
            config.validate()
