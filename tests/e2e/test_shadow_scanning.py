"""
E2E Test: Shadow Scanning

Disabled strategies log what-if opportunities without placing trades.
Tests that the shadow scan pipeline works end-to-end.
"""

import pytest


@pytest.mark.asyncio
async def test_shadow_scan_uses_disabled_strategies(
    trading_bot, mock_client, mock_dashboard
):
    """Shadow scan only runs disabled strategies, not enabled ones."""
    # Verify momentum is disabled
    assert "momentum" in trading_bot.strategy_manager._strategies
    assert trading_bot.strategy_manager._strategies["momentum"].enabled is False

    # Verify mean_reversion is enabled
    assert trading_bot.strategy_manager._strategies["mean_reversion"].enabled is True

    # Add a market
    mock_client.add_market(
        ticker="SHADOW-TEST-01",
        title="Shadow test market",
        yes_bid=30,
        yes_ask=34,
        no_bid=66,
        no_ask=70,
        volume=600,
        series_ticker="TEST",
    )

    # Run shadow scan
    shadow_opps = await trading_bot.strategy_manager.scan_shadow_opportunities(
        existing_positions=trading_bot.open_positions,
    )

    # All shadow opportunities should come from disabled strategies
    for opp in shadow_opps:
        assert opp.strategy_name != "mean_reversion", (
            "Enabled strategy should not appear in shadow scan"
        )


@pytest.mark.asyncio
async def test_shadow_scan_never_trades(
    trading_bot, mock_client, mock_dashboard
):
    """Shadow scan finds opportunities but NEVER executes trades."""
    mock_client.add_market(
        ticker="SHADOW-NOTRADE",
        title="Should not trade this",
        yes_bid=25,
        yes_ask=29,
        no_bid=71,
        no_ask=75,
        volume=800,
        series_ticker="TEST",
    )

    initial_orders = len(mock_client._orders)

    # Run shadow scan via the bot's method
    await trading_bot._shadow_scan()

    # No new orders should have been placed
    assert len(mock_client._orders) == initial_orders, (
        "Shadow scan should never place orders"
    )


@pytest.mark.asyncio
async def test_shadow_opportunities_pushed_to_dashboard(
    trading_bot, mock_client, mock_dashboard
):
    """Shadow opportunities are pushed to dashboard with status='shadow'."""
    mock_client.add_market(
        ticker="SHADOW-DASH",
        title="Dashboard shadow test",
        yes_bid=35,
        yes_ask=39,
        no_bid=61,
        no_ask=65,
        volume=700,
        series_ticker="TEST",
    )

    await trading_bot._shadow_scan()

    # If any shadow opportunities were found, verify they have shadow status
    for opp in mock_dashboard.opportunities:
        if opp["status"] == "shadow":
            assert "[SHADOW]" in (opp.get("reasoning") or "")


@pytest.mark.asyncio
async def test_enabling_strategy_moves_from_shadow(
    trading_bot, mock_client, mock_dashboard, undervalued_market
):
    """When a disabled strategy is enabled, it moves from shadow to real scan."""
    # Initially momentum is disabled
    assert not trading_bot.strategy_manager._strategies["momentum"].enabled

    # Enable it
    trading_bot.strategy_manager.enable_strategy("momentum")
    assert trading_bot.strategy_manager._strategies["momentum"].enabled

    # Now shadow scan should not include momentum
    shadow_opps = await trading_bot.strategy_manager.scan_shadow_opportunities(
        existing_positions={},
    )
    for opp in shadow_opps:
        assert opp.strategy_name != "momentum"
