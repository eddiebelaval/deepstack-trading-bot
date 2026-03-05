"""Tests for CalibrationEdgeStrategy"""

import pytest
from strategies.calibration_edge import (
    CalibrationEdgeStrategy,
    get_calibrated_probability,
    CALIBRATION_TABLE,
)


@pytest.fixture
def strategy():
    return CalibrationEdgeStrategy({})


class TestCalibrationTable:
    def test_exact_lookup(self):
        # 80c market -> 86% true probability
        assert get_calibrated_probability(80) == 0.86

    def test_interpolation(self):
        prob = get_calibrated_probability(75)
        assert 0.78 < prob < 0.80  # Between 70->0.74 and 80->0.86

    def test_bounds(self):
        assert get_calibrated_probability(0) == 0.0
        assert get_calibrated_probability(100) == 1.0

    def test_at_50(self):
        assert get_calibrated_probability(50) == 0.50


class TestScanOpportunities:
    @pytest.mark.asyncio
    async def test_finds_favorite_edge(self, strategy, favorite_market):
        # Market at 80c, calibrated to 86c -> 6c edge, above 3c threshold
        opps = await strategy.scan_opportunities([favorite_market])
        assert len(opps) == 1
        assert opps[0].side == "yes"  # Buy YES on underpriced favorite

    @pytest.mark.asyncio
    async def test_finds_longshot_edge(self, strategy, longshot_market):
        # Market at 20c, calibrated to ~15c -> -5c edge, longshot overpriced
        opps = await strategy.scan_opportunities([longshot_market])
        assert len(opps) == 1
        assert opps[0].side == "no"  # Buy NO on overpriced longshot

    @pytest.mark.asyncio
    async def test_skips_neutral_zone(self, strategy, sample_market):
        # Market at 50c, well-calibrated -> no edge
        opps = await strategy.scan_opportunities([sample_market])
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_skips_closed(self, strategy, closed_market):
        opps = await strategy.scan_opportunities([closed_market])
        assert len(opps) == 0


class TestCheckExit:
    @pytest.mark.asyncio
    async def test_take_profit(self, strategy):
        # Round 4: TP widened to 15c (bonus exit, not primary)
        position = {"entry_price": 80}
        signal = await strategy.check_exit(position, 96)  # +16c > 15c TP
        assert signal.should_exit is True
        assert signal.exit_type == "take_profit"

    @pytest.mark.asyncio
    async def test_stop_loss(self, strategy):
        # Round 4: SL widened to 15c (safety stop for catastrophic moves)
        position = {"entry_price": 80}
        signal = await strategy.check_exit(position, 64)  # -16c > 15c SL
        assert signal.should_exit is True
        assert signal.exit_type == "stop_loss"

    @pytest.mark.asyncio
    async def test_hold_within_safety_range(self, strategy):
        # Price moved -10c but within 15c safety stop — HOLD to settlement
        position = {"entry_price": 80}
        signal = await strategy.check_exit(position, 70)
        assert signal.should_exit is False

    @pytest.mark.asyncio
    async def test_hold(self, strategy):
        position = {"entry_price": 80}
        signal = await strategy.check_exit(position, 82)
        assert signal.should_exit is False


class TestHistoricalStats:
    def test_stats(self, strategy):
        # Round 5: Settlement-realistic priors (80% WR, 15c win, 25c loss)
        stats = strategy.get_historical_stats()
        assert stats["win_rate"] == 0.80
        assert stats["avg_win_cents"] == 15.0
        assert stats["avg_loss_cents"] == 25.0


class TestValidateConfig:
    def test_valid(self, strategy):
        valid, _ = strategy.validate_config()
        assert valid is True

    def test_invalid_thresholds(self):
        s = CalibrationEdgeStrategy({
            "longshot_threshold_cents": 80,
            "favorite_threshold_cents": 70,
        })
        valid, _ = s.validate_config()
        assert valid is False
