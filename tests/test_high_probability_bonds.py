"""Tests for HighProbabilityBondsStrategy"""

import pytest
from strategies.high_probability_bonds import HighProbabilityBondsStrategy


@pytest.fixture
def strategy():
    return HighProbabilityBondsStrategy({})


@pytest.fixture
def custom_strategy():
    return HighProbabilityBondsStrategy({
        "min_probability_cents": 90,
        "max_probability_cents": 97,
        "min_volume": 200,
    })


class TestInit:
    def test_defaults(self, strategy):
        assert strategy.name == "high_probability_bonds"
        assert strategy.min_prob == 93
        assert strategy.max_prob == 98
        assert strategy.take_profit == 2
        assert strategy.stop_loss == 8

    def test_custom_config(self, custom_strategy):
        assert custom_strategy.min_prob == 90
        assert custom_strategy.max_prob == 97


class TestScanOpportunities:
    @pytest.mark.asyncio
    async def test_finds_high_prob(self, strategy, high_prob_market):
        opps = await strategy.scan_opportunities([high_prob_market])
        assert len(opps) == 1
        assert opps[0].side == "yes"
        assert opps[0].entry_price_cents == 96  # yes_ask

    @pytest.mark.asyncio
    async def test_skips_closed(self, strategy, closed_market):
        opps = await strategy.scan_opportunities([closed_market])
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_skips_low_prob(self, strategy, sample_market):
        # Sample market at 50c, below 93c threshold
        opps = await strategy.scan_opportunities([sample_market])
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_skips_existing_positions(self, strategy, high_prob_market):
        existing = {high_prob_market["ticker"]: {}}
        opps = await strategy.scan_opportunities([high_prob_market], existing)
        assert len(opps) == 0


class TestCheckExit:
    @pytest.mark.asyncio
    async def test_take_profit_at_99(self, strategy):
        position = {"entry_price": 95, "side": "yes"}
        signal = await strategy.check_exit(position, 99)
        assert signal.should_exit is True
        assert signal.exit_type == "take_profit"

    @pytest.mark.asyncio
    async def test_stop_loss(self, strategy):
        position = {"entry_price": 95, "side": "yes"}
        signal = await strategy.check_exit(position, 85)
        assert signal.should_exit is True
        assert signal.exit_type == "stop_loss"

    @pytest.mark.asyncio
    async def test_hold(self, strategy):
        position = {"entry_price": 95, "side": "yes"}
        signal = await strategy.check_exit(position, 96)
        assert signal.should_exit is False


class TestHistoricalStats:
    def test_stats(self, strategy):
        stats = strategy.get_historical_stats()
        assert stats["win_rate"] == 0.50
        assert stats["avg_win_cents"] == 6.0
        assert stats["avg_loss_cents"] == 6.0


class TestValidateConfig:
    def test_valid(self, strategy):
        valid, _ = strategy.validate_config()
        assert valid is True

    def test_invalid_min_prob(self):
        s = HighProbabilityBondsStrategy({"min_probability_cents": 50})
        valid, error = s.validate_config()
        assert valid is False
        assert "80" in error

    def test_invalid_max_prob(self):
        s = HighProbabilityBondsStrategy({"max_probability_cents": 99})
        valid, error = s.validate_config()
        assert valid is False
        assert "99" in error
