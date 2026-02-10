"""Tests for NewsSentimentFadeStrategy"""

import pytest
from datetime import datetime, timedelta

from strategies.news_sentiment_fade import NewsSentimentFadeStrategy


@pytest.fixture
def strategy():
    return NewsSentimentFadeStrategy({"enable_llm": False})


class TestInit:
    def test_defaults(self, strategy):
        assert strategy.name == "news_sentiment_fade"
        assert strategy.spike_threshold == 10
        assert strategy.min_volume_surge == 2.0
        assert strategy.max_hold_hours == 4

    def test_llm_disabled(self, strategy):
        assert strategy._llm is None


class TestSpikeDetection:
    def test_no_history(self, strategy):
        result = strategy._detect_spike("TEST", datetime.now())
        assert result is None

    def test_spike_detected(self, strategy):
        now = datetime.now()
        # Simulate price history with a spike
        strategy._price_history["TEST"] = [
            (now - timedelta(minutes=10), 50),
            (now - timedelta(minutes=8), 50),
            (now - timedelta(minutes=6), 51),
            (now - timedelta(minutes=3), 62),  # Spike within window
            (now, 63),
        ]
        result = strategy._detect_spike("TEST", now)
        assert result is not None
        magnitude, pre_spike = result
        assert magnitude >= 10  # At least 10c spike

    def test_no_spike(self, strategy):
        now = datetime.now()
        strategy._price_history["TEST"] = [
            (now - timedelta(minutes=10), 50),
            (now - timedelta(minutes=6), 51),
            (now, 52),  # Only 2c move
        ]
        result = strategy._detect_spike("TEST", now)
        assert result is None


class TestVolumeSurge:
    def test_surge_calculated(self, strategy):
        now = datetime.now()
        strategy._volume_history["TEST"] = [
            (now - timedelta(minutes=10), 100),
            (now - timedelta(minutes=8), 120),
            (now - timedelta(minutes=6), 110),
            (now - timedelta(minutes=2), 300),  # Surge in recent window
            (now, 350),
        ]
        surge = strategy._calculate_volume_surge("TEST", now)
        assert surge > 1.0  # Should detect surge

    def test_no_surge(self, strategy):
        now = datetime.now()
        strategy._volume_history["TEST"] = [
            (now - timedelta(minutes=10), 100),
            (now - timedelta(minutes=2), 100),
            (now, 100),
        ]
        surge = strategy._calculate_volume_surge("TEST", now)
        assert surge <= 1.5  # No significant surge


class TestCheckExit:
    @pytest.mark.asyncio
    async def test_take_profit(self, strategy):
        position = {"entry_price": 50}
        signal = await strategy.check_exit(position, 56)
        assert signal.should_exit is True
        assert signal.exit_type == "take_profit"

    @pytest.mark.asyncio
    async def test_stop_loss(self, strategy):
        position = {"entry_price": 50}
        signal = await strategy.check_exit(position, 45)
        assert signal.should_exit is True
        assert signal.exit_type == "stop_loss"

    @pytest.mark.asyncio
    async def test_time_based_exit(self, strategy):
        entry_time = (datetime.now() - timedelta(hours=5)).isoformat()
        position = {
            "entry_price": 50,
            "metadata": {"entry_time": entry_time},
        }
        signal = await strategy.check_exit(position, 51)
        assert signal.should_exit is True
        assert "hold time" in signal.reason.lower() or "max" in signal.reason.lower()

    @pytest.mark.asyncio
    async def test_hold(self, strategy):
        position = {"entry_price": 50, "metadata": {}}
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

    def test_invalid_spike(self):
        s = NewsSentimentFadeStrategy({"spike_threshold_cents": 1, "enable_llm": False})
        valid, _ = s.validate_config()
        assert valid is False
