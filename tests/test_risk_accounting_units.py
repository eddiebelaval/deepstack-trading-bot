import types

import pytest

from kalshi_trader.main import KalshiTradingBot


class _FakeClient:
    async def create_limit_order(self, **kwargs):
        return {"order_id": "o1"}


class _FakeJournal:
    def log_trade(self, **kwargs):
        return "t1"


class _FakeRisk:
    def __init__(self):
        self.opened = []

    def record_position_open(self, ticker: str, position_size_dollars: float) -> None:
        self.opened.append((ticker, position_size_dollars))


@pytest.mark.asyncio
async def test_place_trade_records_position_cost_in_dollars():
    bot = KalshiTradingBot.__new__(KalshiTradingBot)
    bot.dry_run = False
    bot.client = _FakeClient()
    bot.journal = _FakeJournal()
    bot.risk = _FakeRisk()
    bot.strategy_manager = None
    bot.open_positions = {}

    opp = types.SimpleNamespace(
        side="yes",
        entry_price_cents=40,
        score=99.0,
        reasoning="test",
        metadata={},
    )

    ok = await bot._place_trade("TEST", opp, contracts=10, strategy_name="unit")
    assert ok is True

    # 10 contracts at 40c costs $4.00
    assert bot.open_positions["TEST"]["position_cost_dollars"] == 4.0
    assert bot.risk.opened == [("TEST", 4.0)]

