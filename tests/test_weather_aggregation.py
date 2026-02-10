"""Tests for WeatherAggregationStrategy"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

from strategies.weather_aggregation import WeatherAggregationStrategy
from strategies.data_providers.weather import (
    WeatherForecast,
    parse_kalshi_weather_ticker,
    WeatherDataProvider,
)


class TestParseKalshiWeatherTicker:
    def test_high_temp_nyc(self):
        result = parse_kalshi_weather_ticker("HIGHNY-26FEB08-T40")
        assert result is not None
        assert result["city"] == "new_york"
        assert result["threshold_f"] == 40
        assert result["direction"] == "high"

    def test_low_temp_chicago(self):
        result = parse_kalshi_weather_ticker("LOWCHI-26FEB10-T20")
        assert result is not None
        assert result["city"] == "chicago"
        assert result["threshold_f"] == 20
        assert result["direction"] == "low"

    def test_invalid_ticker(self):
        assert parse_kalshi_weather_ticker("INXD-26FEB07-5000") is None

    def test_unknown_city(self):
        assert parse_kalshi_weather_ticker("HIGHXYZ-26FEB08-T40") is None


class TestWeatherForecast:
    def test_probability_above(self):
        forecast = WeatherForecast(
            city="new_york",
            date=datetime.now(),
            temp_high_f=50.0,
            temp_low_f=30.0,
            temp_std_f=3.0,
        )
        # 50F high, asking about above 40F -> should be very high
        prob = forecast.probability_above(40.0)
        assert prob > 0.95

        # Asking about above 60F -> should be low
        prob = forecast.probability_above(60.0)
        assert prob < 0.05

    def test_probability_below(self):
        forecast = WeatherForecast(
            city="new_york",
            date=datetime.now(),
            temp_high_f=50.0,
            temp_low_f=30.0,
            temp_std_f=3.0,
        )
        # 30F low, asking about below 40F -> should be very high
        prob = forecast.probability_below(40.0)
        assert prob > 0.95


class TestWeatherDataProvider:
    def test_model_consensus_single_source(self):
        provider = WeatherDataProvider()
        forecast = WeatherForecast(
            city="new_york",
            date=datetime.now(),
            temp_high_f=50.0,
            temp_low_f=30.0,
            sources=["nws"],
        )
        assert provider.model_consensus(forecast) == 0.5

    def test_model_consensus_multiple_sources(self):
        provider = WeatherDataProvider()
        forecast = WeatherForecast(
            city="new_york",
            date=datetime.now(),
            temp_high_f=50.0,
            temp_low_f=30.0,
            temp_std_f=2.0,
            sources=["nws", "open_meteo"],
        )
        consensus = provider.model_consensus(forecast)
        assert consensus > 0.5  # Should be higher than single source


class TestWeatherStrategy:
    @pytest.fixture
    def strategy(self):
        return WeatherAggregationStrategy({})

    def test_init(self, strategy):
        assert strategy.name == "weather_aggregation"
        assert strategy.min_edge == 5
        assert "new_york" in strategy.target_cities

    @pytest.mark.asyncio
    async def test_skips_non_weather(self, strategy, sample_market):
        opps = await strategy.scan_opportunities([sample_market])
        assert len(opps) == 0  # Not a weather ticker

    def test_validate_config_valid(self, strategy):
        valid, _ = strategy.validate_config()
        assert valid is True

    def test_validate_config_invalid(self):
        s = WeatherAggregationStrategy({"min_edge_cents": 0})
        valid, _ = s.validate_config()
        assert valid is False

    def test_historical_stats(self, strategy):
        stats = strategy.get_historical_stats()
        assert stats["win_rate"] == 0.50
