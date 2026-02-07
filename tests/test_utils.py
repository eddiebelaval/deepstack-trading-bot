"""Tests for strategies/utils.py"""

import pytest
from strategies.utils import (
    get_mid_price,
    score_spread,
    score_volume,
    hours_until_close,
    is_market_tradeable,
    clamp_score,
)


class TestGetMidPrice:
    def test_with_bid_ask(self):
        market = {"yes_bid": 48, "yes_ask": 52}
        assert get_mid_price(market) == 50

    def test_fallback_to_last_price(self):
        market = {"yes_bid": 0, "yes_ask": 0, "last_price": 65}
        assert get_mid_price(market) == 65

    def test_default_50(self):
        market = {}
        assert get_mid_price(market) == 50


class TestScoreSpread:
    def test_tight_spread(self):
        assert score_spread(49, 50, 50, 51) == 30.0

    def test_wide_spread(self):
        assert score_spread(40, 50, 40, 50) == 0.0

    def test_custom_max_score(self):
        assert score_spread(49, 50, 50, 51, max_score=20.0) == 20.0

    def test_missing_prices(self):
        # Defaults to spread of 10 -> score of 0
        assert score_spread(0, 0, 0, 0) == 0.0


class TestScoreVolume:
    def test_at_target(self):
        assert score_volume(1000, target=1000) == 30.0

    def test_above_target(self):
        assert score_volume(5000, target=1000) == 30.0  # Capped at max

    def test_half_target(self):
        assert score_volume(500, target=1000) == 15.0

    def test_zero_volume(self):
        assert score_volume(0, target=1000) == 0.0


class TestHoursUntilClose:
    def test_no_close_time(self):
        assert hours_until_close({}) is None

    def test_with_valid_time(self, sample_market):
        hours = hours_until_close(sample_market)
        assert hours is not None
        assert 23 < hours < 25  # ~24 hours


class TestIsMarketTradeable:
    def test_open_market(self, sample_market):
        assert is_market_tradeable(sample_market) is True

    def test_closed_market(self, closed_market):
        assert is_market_tradeable(closed_market) is False

    def test_low_volume(self, low_volume_market):
        assert is_market_tradeable(low_volume_market) is False

    def test_custom_min_volume(self, sample_market):
        assert is_market_tradeable(sample_market, min_volume=5000) is False


class TestClampScore:
    def test_within_range(self):
        assert clamp_score(50.0) == 50.0

    def test_below_min(self):
        assert clamp_score(-10.0) == 0.0

    def test_above_max(self):
        assert clamp_score(150.0) == 100.0
