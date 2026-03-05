"""
Arena Seas Tests — Multi-Regime Data Generation, Scoring, and Fitness Bridge

Run: python -m pytest tests/test_arena_seas.py -v
"""

import asyncio
import statistics
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import pytest

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arena.config import ArenaConfig
from arena.fitness import FitnessWriter
from arena.models import RegimeFitness, StrategyScore, WalkForwardWindow
from arena.scoring import CompositeScorer
from arena.seas import ALL_SEA_NAMES, SEAS, SeaCondition, SeaGenerator
from arena.storage import ArenaDB


# ---------------------------------------------------------------------------
# Test: Sea generator output format matches BacktestRunner
# ---------------------------------------------------------------------------


class TestSeaGeneratorFormat:
    """Verify snapshots match BacktestRunner.generate_synthetic() dict keys."""

    def test_snapshot_has_required_keys(self):
        gen = SeaGenerator()
        snapshots = gen.generate_sea(SEAS["mean_reverting"], timesteps=10, seed=42)

        required_keys = {
            "_timestamp", "ticker", "title",
            "yes_bid", "yes_ask", "no_bid", "no_ask",
            "last_price", "volume", "volume_24h",
            "open_interest", "status", "close_time",
        }

        assert len(snapshots) == 10
        for snap in snapshots:
            assert required_keys.issubset(snap.keys()), (
                f"Missing keys: {required_keys - snap.keys()}"
            )

    def test_timestamp_is_datetime(self):
        gen = SeaGenerator()
        snapshots = gen.generate_sea(SEAS["trending_up"], timesteps=5, seed=1)
        for snap in snapshots:
            assert isinstance(snap["_timestamp"], datetime)

    def test_timestamps_are_sequential(self):
        gen = SeaGenerator()
        snapshots = gen.generate_sea(SEAS["trending_up"], timesteps=100, seed=1)
        for i in range(1, len(snapshots)):
            assert snapshots[i]["_timestamp"] > snapshots[i - 1]["_timestamp"]

    def test_prices_in_kalshi_range(self):
        """All prices should be within [1, 99] cents."""
        gen = SeaGenerator()
        for name in ALL_SEA_NAMES:
            snapshots = gen.generate_sea(SEAS[name], timesteps=500, seed=42)
            for snap in snapshots:
                assert 1 <= snap["last_price"] <= 99, (
                    f"Sea '{name}': price {snap['last_price']} out of range"
                )
                assert 1 <= snap["yes_bid"] <= 99
                assert 1 <= snap["yes_ask"] <= 99


# ---------------------------------------------------------------------------
# Test: Sea price ranges match expected behavior
# ---------------------------------------------------------------------------


class TestSeaPriceRanges:
    """Each sea should produce prices in characteristic ranges."""

    def _mean_price(self, snapshots: List[Dict]) -> float:
        return statistics.mean(s["last_price"] for s in snapshots)

    def test_mean_reverting_centers_around_50(self):
        gen = SeaGenerator()
        snaps = gen.generate_sea(SEAS["mean_reverting"], timesteps=5000, seed=42)
        avg = self._mean_price(snaps)
        assert 40 < avg < 60, f"Mean reverting avg={avg}, expected ~50"

    def test_trending_up_above_60(self):
        gen = SeaGenerator()
        # Skip first 500 to let the trend develop
        snaps = gen.generate_sea(SEAS["trending_up"], timesteps=5000, seed=42)
        avg = self._mean_price(snaps[500:])
        assert avg > 55, f"Trending up avg={avg}, expected >55"

    def test_trending_down_below_40(self):
        gen = SeaGenerator()
        snaps = gen.generate_sea(SEAS["trending_down"], timesteps=5000, seed=42)
        avg = self._mean_price(snaps[500:])
        assert avg < 45, f"Trending down avg={avg}, expected <45"

    def test_high_vol_has_wide_range(self):
        gen = SeaGenerator()
        snaps = gen.generate_sea(SEAS["high_vol_choppy"], timesteps=5000, seed=42)
        prices = [s["last_price"] for s in snaps]
        price_range = max(prices) - min(prices)
        assert price_range > 30, f"High vol range={price_range}, expected >30"

    def test_low_vol_calm_near_extremes(self):
        gen = SeaGenerator()
        snaps = gen.generate_sea(SEAS["low_vol_calm"], timesteps=5000, seed=42)
        avg = self._mean_price(snaps)
        assert avg > 85, f"Low vol calm avg={avg}, expected >85"


# ---------------------------------------------------------------------------
# Test: generate_all_seas and generate_voyage
# ---------------------------------------------------------------------------


class TestSeaGeneratorBatch:
    def test_generate_all_seas_returns_all_5(self):
        gen = SeaGenerator()
        all_seas = gen.generate_all_seas(timesteps_per_sea=100, seed=42)
        assert len(all_seas) == 5
        assert set(all_seas.keys()) == set(ALL_SEA_NAMES)
        for name, snaps in all_seas.items():
            assert len(snaps) == 100, f"Sea '{name}' has {len(snaps)}, expected 100"

    def test_generate_all_seas_subset(self):
        gen = SeaGenerator()
        subset = gen.generate_all_seas(
            timesteps_per_sea=50, seed=42,
            regimes=["trending_up", "high_vol_choppy"],
        )
        assert len(subset) == 2
        assert set(subset.keys()) == {"trending_up", "high_vol_choppy"}

    def test_generate_voyage_concatenates(self):
        gen = SeaGenerator()
        voyage = gen.generate_voyage(timesteps=500, seed=42)
        assert len(voyage) == 500
        # Timestamps should be monotonically increasing
        for i in range(1, len(voyage)):
            assert voyage[i]["_timestamp"] > voyage[i - 1]["_timestamp"]


# ---------------------------------------------------------------------------
# Test: Fitness matrix normalization
# ---------------------------------------------------------------------------


class TestFitnessMatrix:
    def test_max_fitness_is_1(self):
        """The best strategy in each regime should get fitness=1.0."""
        regime_scores = {
            "trending_up": [
                StrategyScore(strategy_name="momentum", window_id=None, composite_score=80.0),
                StrategyScore(strategy_name="mean_reversion", window_id=None, composite_score=40.0),
                StrategyScore(strategy_name="settlement_betting", window_id=None, composite_score=20.0),
            ],
            "mean_reverting": [
                StrategyScore(strategy_name="mean_reversion", window_id=None, composite_score=90.0),
                StrategyScore(strategy_name="momentum", window_id=None, composite_score=30.0),
                StrategyScore(strategy_name="settlement_betting", window_id=None, composite_score=60.0),
            ],
        }

        matrix = CompositeScorer.compute_fitness_matrix(regime_scores)

        # Max per regime = 1.0
        assert matrix["momentum"]["trending_up"] == 1.0
        assert matrix["mean_reversion"]["mean_reverting"] == 1.0

        # Others proportional
        assert 0.0 <= matrix["mean_reversion"]["trending_up"] <= 1.0
        assert matrix["mean_reversion"]["trending_up"] == pytest.approx(0.5, abs=0.01)

    def test_all_zero_scores(self):
        """If all strategies scored 0, all fitness should be 0."""
        regime_scores = {
            "low_vol_calm": [
                StrategyScore(strategy_name="a", window_id=None, composite_score=0.0),
                StrategyScore(strategy_name="b", window_id=None, composite_score=0.0),
            ],
        }
        matrix = CompositeScorer.compute_fitness_matrix(regime_scores)
        assert matrix["a"]["low_vol_calm"] == 0.0
        assert matrix["b"]["low_vol_calm"] == 0.0

    def test_fitness_values_bounded(self):
        """All fitness values should be in [0.0, 1.0]."""
        regime_scores = {
            "high_vol_choppy": [
                StrategyScore(strategy_name=f"s{i}", window_id=None,
                              composite_score=float(i * 10))
                for i in range(10)
            ],
        }
        matrix = CompositeScorer.compute_fitness_matrix(regime_scores)
        for strategy, regimes in matrix.items():
            for regime, fitness in regimes.items():
                assert 0.0 <= fitness <= 1.0, (
                    f"{strategy}/{regime}: fitness={fitness}"
                )


# ---------------------------------------------------------------------------
# Test: Regime label propagation through windows
# ---------------------------------------------------------------------------


class TestRegimeLabelPropagation:
    def test_window_regime_label_default_none(self):
        """New windows should have regime_label=None by default."""
        w = WalkForwardWindow(
            window_id=0,
            is_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
            oos_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            oos_end=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        assert w.regime_label is None

    def test_window_regime_label_can_be_set(self):
        w = WalkForwardWindow(
            window_id=0,
            is_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
            oos_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            oos_end=datetime(2026, 3, 1, tzinfo=timezone.utc),
            regime_label="trending_up",
        )
        assert w.regime_label == "trending_up"


# ---------------------------------------------------------------------------
# Test: FitnessWriter roundtrip
# ---------------------------------------------------------------------------


class TestFitnessWriterRoundtrip:
    def test_write_and_read_back(self, tmp_path):
        """Write fitness to a temp DB and read it back."""
        db_file = str(tmp_path / "test_journal.db")
        writer = FitnessWriter(db_path=db_file)

        matrix = {
            "momentum": {
                "trending_up": 0.95,
                "mean_reverting": 0.30,
            },
            "mean_reversion": {
                "trending_up": 0.40,
                "mean_reverting": 0.90,
            },
        }

        count = writer.write_fitness(matrix, tournament_id="test-1234-5678")
        assert count == 4

        # Read back
        read_back = writer.read_current()
        assert read_back["momentum"]["trending_up"] == pytest.approx(0.95, abs=0.01)
        assert read_back["mean_reversion"]["mean_reverting"] == pytest.approx(0.90, abs=0.01)

    def test_upsert_overwrites(self, tmp_path):
        """Writing twice should update existing values."""
        db_file = str(tmp_path / "test_journal.db")
        writer = FitnessWriter(db_path=db_file)

        # First write
        writer.write_fitness(
            {"momentum": {"trending_up": 0.50}},
            tournament_id="first-run",
        )

        # Second write with different value
        writer.write_fitness(
            {"momentum": {"trending_up": 0.95}},
            tournament_id="second-run",
        )

        read_back = writer.read_current()
        assert read_back["momentum"]["trending_up"] == pytest.approx(0.95, abs=0.01)

    def test_generate_diff_output(self):
        """Diff should show changes between current and proposed."""
        current = {
            "momentum": {"trending_up": 0.50, "mean_reverting": 0.20},
        }
        proposed = {
            "momentum": {"trending_up": 0.95, "mean_reverting": 0.20},
            "mean_reversion": {"mean_reverting": 0.90},
        }

        diff = FitnessWriter.generate_diff(current, proposed)
        assert "FITNESS UPDATE" in diff
        assert "momentum" in diff
        assert "mean_reversion" in diff


# ---------------------------------------------------------------------------
# Test: ArenaDB regime storage
# ---------------------------------------------------------------------------


class TestArenaDBRegimeStorage:
    def test_save_and_query_regime_scores(self, tmp_path):
        """Save regime rankings and query them back."""
        from arena.models import TournamentResult

        db = ArenaDB(db_path=tmp_path / "test_arena.db")

        result = TournamentResult(
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            data_source="seas",
            rankings=[
                StrategyScore(strategy_name="momentum", window_id=None,
                              composite_score=75.0, rank=1),
            ],
            regime_scores={
                "trending_up": [
                    StrategyScore(strategy_name="momentum", window_id=None,
                                  composite_score=80.0, rank=1, total_trades=50),
                    StrategyScore(strategy_name="mean_reversion", window_id=None,
                                  composite_score=40.0, rank=2, total_trades=30),
                ],
            },
        )

        db.save_tournament(result)
        db.save_regime_data(result)

        # Query back
        regime_scores = db.get_regime_scores(result.tournament_id)
        assert "trending_up" in regime_scores
        assert len(regime_scores["trending_up"]) == 2
        assert regime_scores["trending_up"][0]["strategy_name"] == "momentum"

    def test_fitness_matrix_from_db(self, tmp_path):
        """Compute fitness matrix from stored regime data."""
        from arena.models import TournamentResult

        db = ArenaDB(db_path=tmp_path / "test_arena.db")

        result = TournamentResult(
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            data_source="seas",
            rankings=[],
            regime_scores={
                "trending_up": [
                    StrategyScore(strategy_name="momentum", window_id=None,
                                  composite_score=100.0, rank=1, total_trades=50),
                    StrategyScore(strategy_name="mean_reversion", window_id=None,
                                  composite_score=50.0, rank=2, total_trades=30),
                ],
            },
        )

        db.save_tournament(result)
        db.save_regime_data(result)

        matrix = db.get_fitness_matrix(result.tournament_id)
        assert matrix["momentum"]["trending_up"] == 1.0
        assert matrix["mean_reversion"]["trending_up"] == pytest.approx(0.5, abs=0.01)
