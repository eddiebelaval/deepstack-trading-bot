"""
Shared test fixtures for strategy tests.
"""

import pytest
from datetime import datetime, timedelta, timezone


@pytest.fixture
def sample_market():
    """A basic open market with good liquidity."""
    return {
        "ticker": "TEST-26FEB07-50",
        "title": "Test market for unit tests",
        "status": "open",
        "yes_bid": 48,
        "yes_ask": 52,
        "no_bid": 48,
        "no_ask": 52,
        "volume": 1000,
        "volume_24h": 1000,
        "last_price": 50,
        "close_time": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "expiration_time": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "event_ticker": "TEST-EVENT",
        "series_ticker": "TEST",
    }


@pytest.fixture
def high_prob_market():
    """A market priced at 95c (high probability YES)."""
    return {
        "ticker": "HIGHPROB-26FEB07",
        "title": "Will the sun rise tomorrow?",
        "status": "open",
        "yes_bid": 94,
        "yes_ask": 96,
        "no_bid": 4,
        "no_ask": 6,
        "volume": 2000,
        "volume_24h": 2000,
        "last_price": 95,
        "close_time": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
    }


@pytest.fixture
def favorite_market():
    """A market at 80c (favorite zone for calibration edge)."""
    return {
        "ticker": "FAV-26FEB07",
        "title": "Favorite market test",
        "status": "open",
        "yes_bid": 78,
        "yes_ask": 82,
        "no_bid": 18,
        "no_ask": 22,
        "volume": 800,
        "close_time": (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat(),
    }


@pytest.fixture
def longshot_market():
    """A market at 20c (longshot zone for calibration edge)."""
    return {
        "ticker": "LONG-26FEB07",
        "title": "Longshot market test",
        "status": "open",
        "yes_bid": 18,
        "yes_ask": 22,
        "no_bid": 78,
        "no_ask": 82,
        "volume": 600,
        "close_time": (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat(),
    }


@pytest.fixture
def weather_market():
    """A Kalshi weather market ticker."""
    return {
        "ticker": "HIGHNY-26FEB08-T40",
        "title": "NYC high temp above 40F on Feb 8",
        "status": "open",
        "yes_bid": 58,
        "yes_ask": 62,
        "no_bid": 38,
        "no_ask": 42,
        "volume": 500,
        "close_time": (datetime.now(timezone.utc) + timedelta(hours=36)).isoformat(),
    }


@pytest.fixture
def implication_markets():
    """Two markets where A implies B but P(A) > P(B) — a violation."""
    return [
        {
            "ticker": "TRUMP-WIN-26",
            "title": "Will Trump win the 2026 election?",
            "status": "open",
            "yes_bid": 53,
            "yes_ask": 57,
            "no_bid": 43,
            "no_ask": 47,
            "volume": 5000,
        },
        {
            "ticker": "GOP-WIN-26",
            "title": "Will Republican win the 2026 election?",
            "status": "open",
            "yes_bid": 48,
            "yes_ask": 52,
            "no_bid": 48,
            "no_ask": 52,
            "volume": 3000,
        },
    ]


@pytest.fixture
def crypto_market():
    """A crypto price prediction market."""
    return {
        "ticker": "BTC-100K-26FEB",
        "title": "Will BTC be above $100,000 by end of February?",
        "status": "open",
        "yes_bid": 43,
        "yes_ask": 47,
        "no_bid": 53,
        "no_ask": 57,
        "volume": 1500,
        "close_time": (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(),
    }


@pytest.fixture
def closed_market():
    """A closed market that should be filtered out."""
    return {
        "ticker": "CLOSED-MKT",
        "title": "Closed market",
        "status": "closed",
        "yes_bid": 50,
        "yes_ask": 50,
        "volume": 0,
    }


@pytest.fixture
def low_volume_market():
    """A market with insufficient volume."""
    return {
        "ticker": "LOWVOL-MKT",
        "title": "Low volume market",
        "status": "open",
        "yes_bid": 48,
        "yes_ask": 52,
        "volume": 5,
    }
