"""
E2E Test: Risk Enforcement

Tests daily loss limit, emotional firewall revenge detection,
and risk check integration with the trading cycle.
"""

import pytest


@pytest.mark.asyncio
async def test_daily_loss_limit_blocks_trades(
    trading_bot, mock_client, undervalued_market
):
    """When daily loss limit is hit, trading cycle skips new trades."""
    from datetime import datetime

    # Simulate having hit the daily loss limit
    # Must also set trading_date to today so _check_daily_reset() doesn't wipe it
    trading_bot.risk.trading_date = datetime.now().strftime("%Y-%m-%d")
    trading_bot.risk.daily_pnl = -100.0  # Equals daily_loss_limit
    trading_bot.risk.daily_trades = 5

    await trading_bot._trading_cycle()

    # No new orders should be placed
    executed = [o for o in mock_client._orders.values() if o["status"] == "executed"]
    assert len(executed) == 0, "Should not trade when daily loss limit is hit"


@pytest.mark.asyncio
async def test_daily_loss_resets_on_new_day(trading_bot):
    """Daily loss tracking resets when the date changes."""
    trading_bot.risk.daily_pnl = -50.0
    trading_bot.risk.trading_date = "2020-01-01"  # Force old date

    # _check_daily_reset should detect new day
    trading_bot.risk._check_daily_reset()

    assert trading_bot.risk.daily_pnl == 0.0
    assert trading_bot.risk.daily_trades == 0


@pytest.mark.asyncio
async def test_risk_check_allows_normal_trades(
    trading_bot, mock_client, undervalued_market
):
    """Normal conditions: risk check passes and trade executes."""
    result = trading_bot.risk.check_trade_allowed("TEST-TICKER", position_size=10.0)
    assert result["allowed"] is True
    assert len(result["reasons"]) == 0


@pytest.mark.asyncio
async def test_risk_check_blocks_oversized_position(trading_bot):
    """Risk check blocks trades that exceed portfolio capacity."""
    # Request a position that's way too large
    result = trading_bot.risk.check_trade_allowed(
        "TEST-TICKER",
        position_size=500.0,  # Way above $250 balance
    )
    assert result["allowed"] is False
    assert any("capacity" in r.lower() for r in result["reasons"])


@pytest.mark.asyncio
async def test_emotional_firewall_records_trades(
    trading_bot, mock_client, undervalued_market
):
    """Trade results are recorded in the emotional firewall."""
    # Record a losing trade
    trading_bot.risk.record_trade_result(
        ticker="TEST-LOSS",
        profit_loss_cents=-500,
        position_size_dollars=10.0,
    )

    stats = trading_bot.risk.get_daily_stats()
    assert stats["daily_pnl"] < 0
    assert stats["daily_trades"] == 1


@pytest.mark.asyncio
async def test_trade_blocked_after_loss_limit(
    trading_bot, mock_client, undervalued_market
):
    """After recording enough losses to hit the limit, new trades are blocked."""
    # Record losses that exceed daily limit ($100)
    for _ in range(5):
        trading_bot.risk.record_trade_result(
            ticker="TEST-LOSS",
            profit_loss_cents=-2500,  # -$25 each
            position_size_dollars=25.0,
        )

    # Daily PnL should be -$125, exceeding $100 limit
    assert trading_bot.risk.daily_pnl <= -100.0

    # Now trading cycle should be blocked
    await trading_bot._trading_cycle()

    executed = [o for o in mock_client._orders.values() if o["status"] == "executed"]
    assert len(executed) == 0
