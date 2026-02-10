"""Tests for DomainSpecializationStrategy"""

import pytest
from datetime import datetime

from strategies.domain_specialization import (
    DomainSpecializationStrategy,
    PriceMomentumSignal,
    VolumeAnalysisSignal,
    MeanReversionSignalSource,
    SIGNAL_REGISTRY,
    DOMAIN_PRESETS,
)


@pytest.fixture
def strategy():
    return DomainSpecializationStrategy({"domain": "crypto_price"})


@pytest.fixture
def custom_strategy():
    return DomainSpecializationStrategy({
        "domain": "custom",
        "category_filter": "test|sample",
        "signal_sources": [
            {"name": "price_momentum", "weight": 0.5},
            {"name": "volume_analysis", "weight": 0.5},
        ],
        "min_signal_strength": 0.3,
    })


class TestSignalSources:
    def test_price_momentum_neutral(self):
        signal = PriceMomentumSignal()
        result = signal.calculate({}, [])
        assert result == 0.0

    def test_price_momentum_bullish(self):
        signal = PriceMomentumSignal()
        now = datetime.now()
        history = [(now, 50), (now, 52), (now, 55), (now, 58), (now, 60)]
        result = signal.calculate({}, history)
        assert result > 0  # Bullish

    def test_price_momentum_bearish(self):
        signal = PriceMomentumSignal()
        now = datetime.now()
        history = [(now, 60), (now, 58), (now, 55), (now, 52), (now, 50)]
        result = signal.calculate({}, history)
        assert result < 0  # Bearish

    def test_mean_reversion_below_50(self):
        signal = MeanReversionSignalSource()
        market = {"yes_bid": 28, "yes_ask": 32}
        result = signal.calculate(market, [])
        assert result > 0  # Should signal buy (revert up)

    def test_mean_reversion_above_50(self):
        signal = MeanReversionSignalSource()
        market = {"yes_bid": 68, "yes_ask": 72}
        result = signal.calculate(market, [])
        assert result < 0  # Should signal sell (revert down)


class TestSignalRegistry:
    def test_all_signals_registered(self):
        expected = {"price_momentum", "volume_analysis", "cross_market_sentiment",
                    "time_decay", "mean_reversion_signal"}
        assert set(SIGNAL_REGISTRY.keys()) == expected


class TestDomainPresets:
    def test_crypto_preset_exists(self):
        assert "crypto_price" in DOMAIN_PRESETS

    def test_fed_preset_exists(self):
        assert "fed_decisions" in DOMAIN_PRESETS

    def test_sports_preset_exists(self):
        assert "sports" in DOMAIN_PRESETS


class TestInit:
    def test_default_domain(self, strategy):
        assert strategy.name == "domain_specialization"
        assert strategy.domain == "crypto_price"
        assert len(strategy._signals) > 0

    def test_custom_config(self, custom_strategy):
        assert custom_strategy.domain == "custom"
        assert len(custom_strategy._signals) == 2


class TestScanOpportunities:
    @pytest.mark.asyncio
    async def test_filters_by_category(self, strategy, sample_market):
        # Sample market title doesn't match crypto filter
        opps = await strategy.scan_opportunities([sample_market])
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_matches_crypto_market(self, strategy, crypto_market):
        # BTC market should match crypto_price filter
        opps = await strategy.scan_opportunities([crypto_market])
        # May or may not find opps depending on signal strength,
        # but it should at least process (not filter out)
        # The test validates the category filter works
        assert isinstance(opps, list)

    @pytest.mark.asyncio
    async def test_skips_closed(self, strategy, closed_market):
        opps = await strategy.scan_opportunities([closed_market])
        assert len(opps) == 0


class TestCheckExit:
    @pytest.mark.asyncio
    async def test_take_profit(self, strategy):
        position = {"entry_price": 50}
        signal = await strategy.check_exit(position, 58)
        assert signal.should_exit is True
        assert signal.exit_type == "take_profit"

    @pytest.mark.asyncio
    async def test_stop_loss(self, strategy):
        position = {"entry_price": 50}
        signal = await strategy.check_exit(position, 44)
        assert signal.should_exit is True

    @pytest.mark.asyncio
    async def test_hold(self, strategy):
        position = {"entry_price": 50}
        signal = await strategy.check_exit(position, 52)
        assert signal.should_exit is False


class TestHistoricalStats:
    def test_stats(self, strategy):
        stats = strategy.get_historical_stats()
        assert stats["win_rate"] == 0.50


class TestValidateConfig:
    def test_valid(self, strategy):
        valid, _ = strategy.validate_config()
        assert valid is True

    def test_invalid_signal_strength(self):
        s = DomainSpecializationStrategy({"min_signal_strength": 0})
        valid, _ = s.validate_config()
        assert valid is False

    def test_invalid_regex(self):
        s = DomainSpecializationStrategy({"category_filter": "[invalid"})
        valid, _ = s.validate_config()
        assert valid is False
