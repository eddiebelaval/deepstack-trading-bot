"""
E2E Test: Bot Lifecycle

Tests initialization, shutdown, graceful cleanup, and component wiring.
"""

import pytest


@pytest.mark.asyncio
async def test_all_components_initialized(trading_bot):
    """All bot components are properly initialized."""
    assert trading_bot.client is not None
    assert trading_bot.risk is not None
    assert trading_bot.journal is not None
    assert trading_bot.performance_tracker is not None
    assert trading_bot.dashboard is not None
    assert trading_bot.strategy_manager is not None
    assert trading_bot.command_processor is not None


@pytest.mark.asyncio
async def test_strategy_manager_has_strategies(trading_bot):
    """Strategy manager has the configured strategies loaded."""
    strategies = trading_bot.strategy_manager._strategies
    assert "mean_reversion" in strategies
    assert "momentum" in strategies
    assert strategies["mean_reversion"].enabled is True
    assert strategies["momentum"].enabled is False


@pytest.mark.asyncio
async def test_shutdown_cancels_orders(
    trading_bot, mock_client, undervalued_market
):
    """Shutdown cancels all resting orders."""
    # Place some orders
    await mock_client.create_limit_order(
        ticker=undervalued_market,
        side="yes",
        action="buy",
        count=5,
        price_cents=45,
    )

    # Create a resting order (disable auto_fill temporarily)
    mock_client.auto_fill = False
    await mock_client.create_limit_order(
        ticker=undervalued_market,
        side="yes",
        action="buy",
        count=3,
        price_cents=40,
    )
    mock_client.auto_fill = True

    resting_before = [
        o for o in mock_client._orders.values() if o["status"] == "resting"
    ]
    assert len(resting_before) >= 1

    # Run shutdown
    await trading_bot._shutdown()

    # All resting orders should be cancelled
    resting_after = [
        o for o in mock_client._orders.values() if o["status"] == "resting"
    ]
    assert len(resting_after) == 0


@pytest.mark.asyncio
async def test_shutdown_generates_summary(trading_bot, mock_client, undervalued_market):
    """Shutdown generates a daily summary in the journal."""
    # Execute a trade first so there's something to summarize
    await trading_bot._trading_cycle()

    # Shutdown
    await trading_bot._shutdown()

    # Journal should be able to generate a summary
    summary = trading_bot.journal.generate_daily_summary()
    assert isinstance(summary, str)


@pytest.mark.asyncio
async def test_bot_paused_skips_scanning(
    trading_bot, mock_client, undervalued_market
):
    """When paused, bot updates state but skips market scanning."""
    trading_bot._paused = True

    await trading_bot._trading_cycle()

    # State should still be updated (dashboard push)
    # But no trades should be executed
    executed = [o for o in mock_client._orders.values() if o["status"] == "executed"]
    assert len(executed) == 0


@pytest.mark.asyncio
async def test_stop_sets_running_false(trading_bot):
    """Calling stop() sets _running to False and triggers shutdown event."""
    assert trading_bot._running is True
    await trading_bot.stop()
    assert trading_bot._running is False
    assert trading_bot._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_position_sync_from_exchange(trading_bot, mock_client):
    """Positions on the exchange are synced to local tracking."""
    # Manually add a position to the mock client
    mock_client._positions["SYNCED-MKT"] = {
        "side": "yes",
        "quantity": 5,
        "avg_price": 50,
        "realized_pnl": 0,
    }
    mock_client.add_market(
        ticker="SYNCED-MKT",
        title="Synced market",
        yes_bid=50,
        yes_ask=54,
        volume=500,
    )

    await trading_bot._sync_positions()

    assert "SYNCED-MKT" in trading_bot.open_positions
    assert trading_bot.open_positions["SYNCED-MKT"]["contracts"] == 5


@pytest.mark.asyncio
async def test_closed_position_removed_on_sync(trading_bot, mock_client):
    """Positions closed on exchange are removed from local tracking."""
    # Add to local tracking
    trading_bot.open_positions["GONE-MKT"] = {
        "side": "yes",
        "contracts": 3,
        "entry_price": 50,
    }

    # Not on the exchange (no position in mock_client._positions)
    await trading_bot._sync_positions()

    assert "GONE-MKT" not in trading_bot.open_positions
