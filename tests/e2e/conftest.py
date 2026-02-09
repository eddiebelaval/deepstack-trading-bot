"""
E2E Test Fixtures — Bot Factory with Mock Wiring

Creates a real KalshiTradingBot with:
- MockKalshiClient (in-memory exchange)
- MockDashboardSync (recording dashboard)
- Real strategies via StrategyManager
- Real TradeJournal + PerformanceTracker (temp SQLite)
- Real DeepStackIntegration (Kelly + Emotional Firewall)

Tests call bot methods directly (_trading_cycle, _manage_positions),
never bot.start() (which runs an infinite loop with signal handlers).
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Ensure DEEPSTACK_PATH is set before any bot imports
DEEPSTACK_PATH = os.getenv(
    "DEEPSTACK_PATH",
    "/Users/eddiebelaval/Development/id8/products/deepstack",
)
if DEEPSTACK_PATH not in sys.path:
    sys.path.insert(0, DEEPSTACK_PATH)

from tests.e2e.mock_kalshi_client import MockKalshiClient
from tests.e2e.mock_dashboard import MockDashboardSync

from kalshi_trader.config import KalshiConfig
from kalshi_trader.main import KalshiTradingBot
from kalshi_trader.journal import TradeJournal
from kalshi_trader.performance_tracker import PerformanceTracker
from kalshi_trader.deepstack_integration import DeepStackIntegration
from kalshi_trader.strategy_manager import StrategyManager
from kalshi_trader.market_cache import get_market_cache
from markets import KalshiMarket


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path for journal + performance tracker."""
    return str(tmp_path / "test_trades.db")


@pytest.fixture
def mock_client():
    """MockKalshiClient with $250 balance and auto-fill enabled."""
    client = MockKalshiClient(initial_balance_cents=25000, auto_fill=True)
    return client


@pytest.fixture
def mock_dashboard():
    """MockDashboardSync for recording push calls."""
    return MockDashboardSync()


@pytest.fixture
def test_config():
    """KalshiConfig with test-safe values."""
    return KalshiConfig(
        api_key_id="test-key-id",
        private_key_path="/tmp/fake_key.pem",
        max_position_size=50.0,
        daily_loss_limit=100.0,
        kelly_fraction=0.5,
        min_position_size=1.0,
        market_series="TEST",
        min_volume=100,
        price_floor_cents=40,
        price_ceiling_cents=60,
        take_profit_cents=8,
        stop_loss_cents=5,
        poll_interval_seconds=10,
        journal_db_path="/tmp/test_journal.db",
    )


@pytest.fixture
def strategy_configs():
    """Strategy configurations for testing. Uses mean_reversion (enabled)
    and momentum (disabled, for shadow scanning tests)."""
    return [
        {
            "name": "mean_reversion",
            "enabled": True,
            "markets": [{"platform": "kalshi", "series": "TEST"}],
            "config": {
                "price_floor_cents": 40,
                "price_ceiling_cents": 60,
                "take_profit_cents": 8,
                "stop_loss_cents": 5,
                "min_volume": 50,
            },
        },
        {
            "name": "momentum",
            "enabled": False,
            "markets": [{"platform": "kalshi", "series": "TEST"}],
            "config": {
                "take_profit_cents": 10,
                "stop_loss_cents": 7,
                "min_volume": 50,
                "lookback_periods": 3,
                "momentum_threshold": 2.0,
            },
        },
    ]


@pytest_asyncio.fixture
async def trading_bot(
    mock_client,
    mock_dashboard,
    test_config,
    strategy_configs,
    tmp_db,
):
    """
    Fully wired trading bot with mock externals.

    Manually initializes components instead of calling bot._initialize()
    (which tries to connect to real APIs).
    """
    # Clear global market cache to prevent inter-test poisoning
    get_market_cache().clear()

    # Override config to use temp db
    test_config.journal_db_path = tmp_db

    # Create bot in multi-strategy mode
    bot = KalshiTradingBot(
        config=test_config,
        use_strategy_manager=True,
        strategy_configs=strategy_configs,
        dry_run=False,
    )

    # Wire mock client
    bot.client = mock_client
    await mock_client.connect()

    # Wire risk management with realistic balance
    bot.risk = DeepStackIntegration(test_config, account_balance=250.0)

    # Wire real strategy manager with mock market adapter
    mock_market = KalshiMarket({}, mock_client)
    bot.market = mock_market

    manager_config = {"strategies": strategy_configs}
    bot.strategy_manager = StrategyManager(
        config=manager_config,
        markets={"kalshi": mock_market},
        max_position_size=test_config.max_position_size,
        dry_run=False,
    )
    await bot.strategy_manager.initialize()

    # Wire real journal (temp db)
    bot.journal = TradeJournal(tmp_db)

    # Wire real performance tracker (same temp db)
    bot.performance_tracker = PerformanceTracker(
        db_path=tmp_db,
        prior_strength=20,
        decay_half_life_days=30.0,
        auto_disable=False,
    )

    # Register priors for all strategies
    bot._register_strategy_priors()

    # Wire mock dashboard
    bot.dashboard = mock_dashboard
    await mock_dashboard.connect()

    # Wire mock command processor (just needs connect/update_mode/poll stubs)
    bot.command_processor = MagicMock()
    bot.command_processor.connect = AsyncMock()
    bot.command_processor.disconnect = AsyncMock()
    bot.command_processor.update_mode = AsyncMock()
    bot.command_processor.poll_and_execute = AsyncMock()
    bot.command_processor.send_heartbeat = AsyncMock()

    # Mark as running (needed for _trading_cycle to not skip)
    bot._running = True
    bot._paused = False

    yield bot

    # Cleanup
    if bot.journal:
        bot.journal.close()
    if bot.performance_tracker:
        bot.performance_tracker.close()
    await mock_client.disconnect()


@pytest.fixture
def undervalued_market(mock_client):
    """Add an undervalued YES market (price at 46c, below fair value).
    Good candidate for mean_reversion strategy."""
    mock_client.add_market(
        ticker="TEST-26FEB08-4600",
        title="Test index above 4600 by Feb 8",
        yes_bid=44,
        yes_ask=48,
        no_bid=52,
        no_ask=56,
        volume=500,
        status="open",
        series_ticker="TEST",
    )
    return "TEST-26FEB08-4600"


@pytest.fixture
def overvalued_market(mock_client):
    """Add an overvalued YES market (price at 56c, above fair value).
    Good candidate for mean_reversion NO trade."""
    mock_client.add_market(
        ticker="TEST-26FEB08-5600",
        title="Test index above 5600 by Feb 8",
        yes_bid=54,
        yes_ask=58,
        no_bid=42,
        no_ask=46,
        volume=600,
        status="open",
        series_ticker="TEST",
    )
    return "TEST-26FEB08-5600"


@pytest.fixture
def multiple_markets(mock_client):
    """Add several markets for testing strategy scanning."""
    tickers = []
    for i, (yb, ya) in enumerate([(44, 48), (38, 42), (55, 59), (50, 54)]):
        ticker = f"TEST-MULTI-{i}"
        mock_client.add_market(
            ticker=ticker,
            title=f"Multi-market test {i}",
            yes_bid=yb,
            yes_ask=ya,
            no_bid=100 - ya,
            no_ask=100 - yb,
            volume=500 + i * 100,
            series_ticker="TEST",
        )
        tickers.append(ticker)
    return tickers
