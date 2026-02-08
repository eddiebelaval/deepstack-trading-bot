import types

import pytest

from kalshi_trader.command_processor import CommandProcessor


class _FakeClient:
    def __init__(self, *, order_result, market=None):
        self._order_result = order_result
        self._market = market or {"yes_bid": 55, "no_bid": 44}

    async def cancel_all_orders(self):
        return 3

    async def get_market(self, ticker: str):
        return dict(self._market)

    async def create_limit_order(self, **kwargs):
        return self._order_result


@pytest.mark.asyncio
async def test_force_close_dry_run_does_not_delete_tracking():
    bot = types.SimpleNamespace()
    bot.dry_run = True
    bot.client = _FakeClient(order_result={"order_id": "ignored"})
    bot.open_positions = {
        "TEST": {"side": "yes", "contracts": 7},
    }

    cp = CommandProcessor(bot)
    res = await cp._handle_force_close({})

    assert res["cancelled_orders"] == 3
    assert res["dry_run"] is True
    assert res["would_close"] == ["TEST"]
    assert bot.open_positions.get("TEST") is not None


@pytest.mark.asyncio
async def test_force_close_does_not_delete_if_order_not_created():
    bot = types.SimpleNamespace()
    bot.dry_run = False
    bot.client = _FakeClient(order_result=None)
    bot.open_positions = {
        "TEST": {"side": "yes", "contracts": 7},
    }

    cp = CommandProcessor(bot)
    res = await cp._handle_force_close({})

    assert res["cancelled_orders"] == 3
    assert res["closed_positions"] == []
    assert bot.open_positions.get("TEST") is not None


@pytest.mark.asyncio
async def test_force_close_deletes_only_on_success():
    bot = types.SimpleNamespace()
    bot.dry_run = False
    bot.client = _FakeClient(order_result={"order_id": "o1"})
    bot.open_positions = {
        "TEST": {"side": "yes", "contracts": 7},
    }

    cp = CommandProcessor(bot)
    res = await cp._handle_force_close({})

    assert res["closed_positions"] == ["TEST"]
    assert "TEST" not in bot.open_positions


@pytest.mark.asyncio
async def test_update_risk_accepts_cents_and_converts_to_dollars():
    bot = types.SimpleNamespace()
    bot.config = types.SimpleNamespace(
        max_position_size=0.0,
        daily_loss_limit=0.0,
        kelly_fraction=0.0,
        poll_interval_seconds=60,
    )
    bot.risk = None

    cp = CommandProcessor(bot)
    res = await cp._handle_update_risk(
        {
            "kelly_fraction": 0.2,
            "max_position_size_cents": 12345,
            "daily_loss_limit_cents": 5000,
        }
    )

    assert res["updated"]["kelly_fraction"] == 0.2
    assert res["updated"]["max_position_size"] == 123.45
    assert res["updated"]["daily_loss_limit"] == 50.0
    assert bot.config.max_position_size == 123.45
    assert bot.config.daily_loss_limit == 50.0


@pytest.mark.asyncio
async def test_set_poll_interval_accepts_interval_seconds_and_clamps():
    bot = types.SimpleNamespace()
    bot.config = types.SimpleNamespace(poll_interval_seconds=60)

    cp = CommandProcessor(bot)
    res = await cp._handle_set_poll_interval({"interval_seconds": 5})
    assert res["poll_interval_seconds"] == 15
    assert bot.config.poll_interval_seconds == 15

    res = await cp._handle_set_poll_interval({"interval_seconds": 600})
    assert res["poll_interval_seconds"] == 300
    assert bot.config.poll_interval_seconds == 300

