"""Tests for TikTokVelocityStrategy"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock

from strategies.tiktok_velocity import (
    TikTokVelocityStrategy,
    HashtagMetrics,
    TrendSignal,
)


@pytest.fixture
def strategy():
    """Basic strategy fixture with default config."""
    return TikTokVelocityStrategy({
        "velocity_threshold": 0.5,
        "sentiment_threshold": 0.2,
        "ema_periods": 5,
        "hashtags": ["recession", "crypto", "inflation"],
    })


@pytest.fixture
def mock_tiktok_data():
    """Sample TikTok hashtag data."""
    return {
        "hashtag": "recession",
        "view_count": 5000000,
        "video_count": 50000,
        "videos": [
            {"desc": "Recession is coming!!! Markets crashing", "likes": 50000},
            {"desc": "Prepare for the worst recession ever", "likes": 30000},
            {"desc": "Recession proof your portfolio now", "likes": 20000},
        ],
        "timestamp": datetime.now().isoformat(),
    }


class TestInit:
    """Test strategy initialization."""

    def test_defaults(self, strategy):
        assert strategy.name == "tiktok_velocity"
        assert strategy.velocity_threshold == 0.5
        assert strategy.sentiment_threshold == 0.2
        assert strategy.take_profit == 12
        assert strategy.stop_loss == 6

    def test_custom_config(self):
        config = {
            "velocity_threshold": 0.8,
            "sentiment_threshold": 0.3,
            "take_profit_cents": 15,
            "stop_loss_cents": 8,
        }
        s = TikTokVelocityStrategy(config)
        assert s.velocity_threshold == 0.8
        assert s.sentiment_threshold == 0.3
        assert s.take_profit == 15
        assert s.stop_loss == 8

    def test_hashtags_loaded(self, strategy):
        assert len(strategy.hashtags) == 3
        assert "recession" in strategy.hashtags

    def test_market_mappings_exist(self, strategy):
        assert "recession" in strategy.market_mappings
        assert "crypto" in strategy.market_mappings


class TestSentimentAnalysis:
    """Test sentiment analysis functionality."""

    def test_bullish_sentiment(self, strategy):
        text = "Market rally incoming! Buy the breakout!"
        score = strategy._analyze_sentiment(text)
        assert score > 0  # Should be positive

    def test_bearish_sentiment(self, strategy):
        text = "Crash imminent! Sell everything! Recession coming!"
        score = strategy._analyze_sentiment(text)
        assert score < 0  # Should be negative

    def test_neutral_sentiment(self, strategy):
        text = "The market is open today"
        score = strategy._analyze_sentiment(text)
        # Neutral-ish


class TestEMACalculation:
    """Test EMA calculation."""

    def test_ema_basic(self, strategy):
        values = [100, 110, 120, 115, 125]
        ema = strategy._calculate_ema(values, periods=3)
        assert ema > 0
        assert isinstance(ema, float)

    def test_ema_single_value(self, strategy):
        values = [100]
        ema = strategy._calculate_ema(values, periods=5)
        assert ema == 100.0

    def test_ema_empty(self, strategy):
        ema = strategy._calculate_ema([], periods=5)
        assert ema == 0.0


class TestVelocityCalculation:
    """Test velocity calculation."""

    def test_velocity_with_growth(self, strategy):
        now = datetime.now()
        metric = HashtagMetrics(hashtag="test")
        metric.samples = [
            (now - timedelta(minutes=30), 1000000, 0.0),
            (now - timedelta(minutes=20), 1200000, 0.1),
            (now - timedelta(minutes=10), 1500000, 0.2),
        ]
        metric.sentiment_score = 0.2
        
        velocity = strategy._calculate_velocity(metric)
        assert velocity > 0  # Should detect growth

    def test_velocity_no_data(self, strategy):
        metric = HashtagMetrics(hashtag="test")
        velocity = strategy._calculate_velocity(metric)
        assert velocity == 0.0


class TestMarketMapping:
    """Test market to hashtag mapping."""

    def test_direct_mapping(self, strategy):
        markets = strategy._map_to_markets("recession")
        assert "INXDJ" in markets

    def test_partial_match(self, strategy):
        markets = strategy._map_to_markets("bitcoin")
        assert "KXBTC" in markets

    def test_no_match(self, strategy):
        markets = strategy._map_to_markets("randomhashtag123")
        assert markets == []


class TestTradeSideDetermination:
    """Test trade side determination."""

    def test_bullish_signal_yes(self, strategy):
        signal = TrendSignal(
            hashtag="crypto",
            keyword="crypto",
            velocity=0.8,
            sentiment=0.5,
            direction="bullish",
            confidence=0.7,
            timestamp=datetime.now(),
        )
        market = {"title": "Will crypto go up?"}
        side = strategy._determine_trade_side(signal, market)
        assert side == "yes"

    def test_bearish_signal_no(self, strategy):
        signal = TrendSignal(
            hashtag="recession",
            keyword="recession",
            velocity=0.8,
            sentiment=-0.5,
            direction="bearish",
            confidence=0.7,
            timestamp=datetime.now(),
        )
        market = {"title": "Will market crash?"}
        side = strategy._determine_trade_side(signal, market)
        assert side == "no"

    def test_inverse_market_logic(self, strategy):
        signal = TrendSignal(
            hashtag="recession",
            keyword="recession",
            velocity=0.8,
            sentiment=-0.5,
            direction="bearish",
            confidence=0.7,
            timestamp=datetime.now(),
        )
        # "No recession" means bullish - bearish sentiment should buy YES
        market = {"title": "Will there be no recession?"}
        side = strategy._determine_trade_side(signal, market)
        assert side == "yes"


class TestOpportunityCreation:
    """Test trading opportunity creation."""

    def test_valid_opportunity(self, strategy):
        signal = TrendSignal(
            hashtag="recession",
            keyword="recession",
            velocity=0.8,
            sentiment=-0.5,
            direction="bearish",
            confidence=0.7,
            timestamp=datetime.now(),
            mapped_markets=["INXDJ"],
        )
        market = {
            "ticker": "INXDJ-25FEB07-4500",
            "title": "Will S&P close above 4500?",
            "status": "open",
            "yes_bid": 48,
            "yes_ask": 52,
            "no_bid": 48,
            "no_ask": 52,
            "volume": 1000,
        }
        
        opp = strategy._create_opportunity(market, signal, 1000)
        assert opp is not None
        assert opp.side == "no"  # Bearish signal
        assert opp.strategy_name == "tiktok_velocity"
        assert "recession" in opp.reasoning

    def test_low_score_filtered(self, strategy):
        signal = TrendSignal(
            hashtag="recession",
            keyword="recession",
            velocity=0.1,  # Very low velocity
            sentiment=-0.1,  # Weak sentiment
            direction="bearish",
            confidence=0.1,
            timestamp=datetime.now(),
        )
        market = {
            "ticker": "TEST-MKT",
            "title": "Test",
            "status": "open",
            "yes_bid": 48,
            "yes_ask": 52,
            "volume": 1000,
        }
        
        opp = strategy._create_opportunity(market, signal, 1000)
        assert opp is None  # Should be filtered by score


@pytest.mark.asyncio
class TestScanOpportunities:
    """Test async market scanning."""

    async def test_scans_all_hashtags(self, strategy):
        strategy._fetch_tiktok_hashtag_data = AsyncMock(return_value={
            "view_count": 1000000,
            "videos": [{"desc": "Test", "likes": 1000}],
        })
        
        markets = []
        await strategy.scan_opportunities(markets)
        
        # Should fetch data for each hashtag
        assert strategy._fetch_tiktok_hashtag_data.call_count == len(strategy.hashtags)

    async def test_respects_existing_positions(self, strategy):
        strategy._fetch_tiktok_hashtag_data = AsyncMock(return_value=None)
        
        markets = [
            {"ticker": "EXISTING", "status": "open", "volume": 1000}
        ]
        existing = {"EXISTING": {"contracts": 10}}
        
        opps = await strategy.scan_opportunities(markets, existing)
        assert len(opps) == 0  # Should skip existing


@pytest.mark.asyncio
class TestCheckExit:
    """Test exit signal checking."""

    async def test_take_profit(self, strategy):
        position = {"entry_price": 50, "metadata": {}}
        signal = await strategy.check_exit(position, 62)  # +12 cents
        assert signal.should_exit is True
        assert signal.exit_type == "take_profit"

    async def test_stop_loss(self, strategy):
        position = {"entry_price": 50, "metadata": {}}
        signal = await strategy.check_exit(position, 44)  # -6 cents
        assert signal.should_exit is True
        assert signal.exit_type == "stop_loss"

    async def test_sentiment_reversal_exit(self, strategy):
        # Setup: original bullish sentiment
        strategy._hashtag_metrics["test"] = HashtagMetrics(
            hashtag="test",
            sentiment_score=-0.5,  # Now bearish
            last_updated=datetime.now(),
        )
        
        position = {
            "entry_price": 50,
            "metadata": {"hashtag": "test", "sentiment": 0.5}  # Was bullish
        }
        signal = await strategy.check_exit(position, 52)
        assert signal.should_exit is True
        assert "reversed" in signal.reason.lower()

    async def test_hold(self, strategy):
        position = {"entry_price": 50, "metadata": {}}
        signal = await strategy.check_exit(position, 52)
        assert signal.should_exit is False
        assert signal.exit_type == "hold"


class TestValidation:
    """Test configuration validation."""

    def test_valid_config(self, strategy):
        valid, error = strategy.validate_config()
        assert valid is True
        assert error == ""

    def test_invalid_velocity_threshold(self):
        s = TikTokVelocityStrategy({"velocity_threshold": 0})
        valid, error = s.validate_config()
        assert valid is False
        assert "velocity_threshold" in error

    def test_invalid_sentiment_threshold(self):
        s = TikTokVelocityStrategy({"sentiment_threshold": 1.5})
        valid, error = s.validate_config()
        assert valid is False

    def test_empty_hashtags(self):
        s = TikTokVelocityStrategy({"hashtags": []})
        valid, error = s.validate_config()
        assert valid is False
        assert "hashtag" in error.lower()


class TestBacktesting:
    """Test backtesting functionality."""

    def test_load_backtest_data(self, strategy):
        data = [
            {"hashtag": "recession", "view_count": 1000000, "timestamp": "2024-01-01T00:00:00"},
            {"hashtag": "recession", "view_count": 1200000, "timestamp": "2024-01-01T01:00:00"},
        ]
        strategy.load_backtest_data(data)
        assert strategy.backtest_mode is True

    def test_reset_backtest(self, strategy):
        strategy._hashtag_metrics["test"] = HashtagMetrics(hashtag="test")
        strategy._scan_counter = 10
        
        strategy.reset_backtest()
        
        assert len(strategy._hashtag_metrics) == 0
        assert strategy._scan_counter == 0


class TestHistoricalStats:
    """Test performance statistics."""

    def test_stats_structure(self, strategy):
        stats = strategy.get_historical_stats()
        assert "win_rate" in stats
        assert "avg_win_cents" in stats
        assert "avg_loss_cents" in stats
        assert stats["win_rate"] == 0.52

    def test_calculate_edge(self, strategy):
        edge = strategy.calculate_edge()
        assert "expected_value_cents" in edge
        assert "kelly_pct" in edge
        assert "win_loss_ratio" in edge


class TestDescription:
    """Test strategy description."""

    def test_description_contains_params(self, strategy):
        desc = strategy.description
        assert "velocity" in desc.lower()
        assert "sentiment" in desc.lower()
