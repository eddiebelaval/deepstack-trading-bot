"""
E2E Test: Full Trade Cycle

Happy path: scan -> trade -> monitor -> exit.
Tests the complete lifecycle from opportunity detection through execution
and position management.
"""

import pytest


@pytest.mark.asyncio
async def test_scan_finds_opportunity(trading_bot, mock_client, undervalued_market):
    """Strategy scan finds an undervalued market and returns opportunities."""
    opps = await trading_bot.strategy_manager.scan_all_opportunities(
        existing_positions=trading_bot.open_positions,
    )
    # Mean reversion should find the undervalued market (44-48c range)
    assert len(opps) > 0
    opp = opps[0]
    assert opp.ticker == undervalued_market
    assert opp.side in ("yes", "no")
    assert 1 <= opp.entry_price_cents <= 99
    assert opp.score > 0


@pytest.mark.asyncio
async def test_trade_executed_after_scan(
    trading_bot, mock_client, mock_dashboard, undervalued_market
):
    """Full cycle: scan -> execute trade -> verify all side effects."""
    # Run a single trading cycle
    await trading_bot._trading_cycle()

    # Verify: mock client has an executed order
    executed_orders = [
        o for o in mock_client._orders.values() if o["status"] == "executed"
    ]
    assert len(executed_orders) >= 1, "Expected at least one executed order"

    order = executed_orders[0]
    assert order["ticker"] == undervalued_market
    assert order["action"] == "buy"

    # Verify: journal has a record
    open_trades = trading_bot.journal.get_open_trades()
    assert len(open_trades) >= 1
    trade = open_trades[0]
    assert trade["market_ticker"] == undervalued_market
    assert trade["status"] == "open"

    # Verify: dashboard received push_trade
    assert len(mock_dashboard.trades) >= 1
    dash_trade = mock_dashboard.trades[0]
    assert dash_trade["market_ticker"] == undervalued_market
    assert dash_trade["action"] == "buy"


@pytest.mark.asyncio
async def test_position_tracked_after_trade(
    trading_bot, mock_client, undervalued_market
):
    """After trade execution, position is tracked in bot.open_positions."""
    await trading_bot._trading_cycle()

    assert undervalued_market in trading_bot.open_positions
    pos = trading_bot.open_positions[undervalued_market]
    assert pos["contracts"] > 0
    assert pos["side"] in ("yes", "no")
    assert "trade_id" in pos
    assert "entry_price" in pos


@pytest.mark.asyncio
async def test_take_profit_exit(trading_bot, mock_client, undervalued_market):
    """Price moves to take profit -> exit signal -> position closed."""
    # Execute entry
    await trading_bot._trading_cycle()
    assert undervalued_market in trading_bot.open_positions

    pos = trading_bot.open_positions[undervalued_market]
    entry_price = pos["entry_price"]

    # Simulate price moving UP by take_profit amount (+8c)
    new_price = entry_price + 8
    mock_client.update_price(
        undervalued_market,
        yes_bid=new_price,
        yes_ask=new_price + 2,
        no_bid=100 - (new_price + 2),
        no_ask=100 - new_price,
    )

    # Run position management
    await trading_bot._manage_positions()

    # Position should be closed (exit signal triggered)
    assert undervalued_market not in trading_bot.open_positions


@pytest.mark.asyncio
async def test_stop_loss_exit(trading_bot, mock_client, undervalued_market):
    """Price moves to stop loss -> exit signal -> position closed."""
    await trading_bot._trading_cycle()
    assert undervalued_market in trading_bot.open_positions

    pos = trading_bot.open_positions[undervalued_market]
    entry_price = pos["entry_price"]

    # Simulate price dropping by stop_loss amount (-5c)
    new_price = max(1, entry_price - 5)
    mock_client.update_price(
        undervalued_market,
        yes_bid=new_price,
        yes_ask=new_price + 2,
        no_bid=100 - (new_price + 2),
        no_ask=100 - new_price,
    )

    await trading_bot._manage_positions()

    assert undervalued_market not in trading_bot.open_positions


@pytest.mark.asyncio
async def test_pnl_calculated_on_close(
    trading_bot, mock_client, mock_dashboard, undervalued_market
):
    """PnL is correctly calculated when position is closed."""
    await trading_bot._trading_cycle()

    pos = trading_bot.open_positions[undervalued_market]
    entry_price = pos["entry_price"]
    trade_id = pos["trade_id"]

    # Move price up for a winning trade
    new_price = entry_price + 8
    mock_client.update_price(
        undervalued_market,
        yes_bid=new_price,
        yes_ask=new_price + 2,
        no_bid=100 - (new_price + 2),
        no_ask=100 - new_price,
    )

    await trading_bot._manage_positions()

    # Check journal has PnL
    trade = trading_bot.journal.get_trade(trade_id)
    if trade and trade.get("status") == "closed":
        assert trade["pnl_cents"] is not None
        # Winning trade should have positive PnL
        assert trade["pnl_cents"] > 0


@pytest.mark.asyncio
async def test_one_trade_per_cycle(trading_bot, mock_client, multiple_markets):
    """Only one trade executed per cycle even with multiple opportunities."""
    await trading_bot._trading_cycle()

    # Count executed orders
    executed = [o for o in mock_client._orders.values() if o["status"] == "executed"]
    assert len(executed) <= 1, f"Expected at most 1 trade per cycle, got {len(executed)}"


@pytest.mark.asyncio
async def test_skip_ticker_with_existing_position(
    trading_bot, mock_client, undervalued_market
):
    """Don't open a second position on a ticker that already has one."""
    # First cycle: opens position
    await trading_bot._trading_cycle()
    assert undervalued_market in trading_bot.open_positions

    initial_orders = len(mock_client._orders)

    # Second cycle: should NOT open another position on same ticker
    await trading_bot._trading_cycle()

    # No new orders for the same ticker
    new_orders = [
        o
        for oid, o in mock_client._orders.items()
        if o["ticker"] == undervalued_market and o["status"] == "executed"
    ]
    assert len(new_orders) <= 1, "Should not open duplicate position"


@pytest.mark.asyncio
async def test_state_pushed_each_cycle(
    trading_bot, mock_client, mock_dashboard, undervalued_market
):
    """Dashboard state is pushed every trading cycle."""
    await trading_bot._trading_cycle()

    assert len(mock_dashboard.states) >= 1
    state = mock_dashboard.states[-1]
    assert "balance_cents" in state
    assert "daily_pnl_cents" in state
    assert "strategies" in state
    assert "risk_config" in state
