"""
Tests for self_knowledge — bot state aggregation for conversational context.

Covers the _get_conn → _get_connection fix (A2) and all gather functions.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, PropertyMock
from types import SimpleNamespace

from kalshi_trader.self_knowledge import (
    gather_self_knowledge,
    _gather_portfolio,
    _gather_strategy_health,
    _gather_regime,
    _gather_risk_state,
    _gather_governance,
    _gather_health,
    _gather_allocation,
    _gather_config,
)


class MockBot:
    """Minimal bot mock for self_knowledge testing."""

    def __init__(self):
        self.risk = MagicMock()
        self.risk.account_balance = 150.0
        self.risk.get_daily_stats.return_value = {
            "daily_pnl": 5.0,
            "daily_pnl_pct": 3.3,
            "daily_trades": 2,
            "loss_limit_remaining": 15.0,
            "can_trade": True,
            "portfolio_heat": 0.12,
            "current_streak": 2,
            "active_cooldown": False,
        }

        self.open_positions = {
            "KXBTC-TEST": {
                "side": "no",
                "contracts": 5,
                "avg_price": 92,
            }
        }
        self._running = True
        self._paused = False
        self.dry_run = False
        self.performance_tracker = None
        self.strategy_manager = None
        self.market_governor = None
        self.config = None
        self.journal = None
        self.captains_log = None
        self.capital_allocator = None
        self._strategy_circuit_breakers = {}
        self._auto_disabled_strategies = set()
        self._inaction_cycles = {}
        self._latest_health = {}
        self.circuit_breaker = None


@pytest.fixture
def bot():
    return MockBot()


class TestGatherPortfolio:
    def test_renders_balance(self, bot):
        result = _gather_portfolio(bot)
        assert "150.00" in result
        assert "Portfolio State" in result

    def test_renders_positions(self, bot):
        result = _gather_portfolio(bot)
        assert "KXBTC-TEST" in result
        assert "5 contracts" in result

    def test_no_risk_module(self, bot):
        bot.risk = None
        result = _gather_portfolio(bot)
        assert "not initialized" in result


class TestGatherRiskState:
    def test_renders_heat(self, bot):
        result = _gather_risk_state(bot)
        assert "12.0%" in result
        assert "Risk Management" in result

    def test_no_active_cooldown(self, bot):
        result = _gather_risk_state(bot)
        assert "No active cooldowns" in result

    def test_circuit_breaker_tripped(self, bot):
        bot._strategy_circuit_breakers = {
            "bad_strat": {"consecutive_losses": 5, "total_pnl_cents": -200}
        }
        result = _gather_risk_state(bot)
        assert "Circuit breaker" in result
        assert "bad_strat" in result


class TestGatherHealth:
    def test_no_health_data(self, bot):
        result = _gather_health(bot)
        assert "No health data" in result

    def test_with_health_data(self, bot):
        bot._latest_health = {
            "api_status": "connected",
            "db_status": "ok",
            "uptime": "2h 15m",
        }
        result = _gather_health(bot)
        assert "connected" in result

    def test_circuit_breaker_open(self, bot):
        cb = MagicMock()
        cb.is_open = True
        bot.circuit_breaker = cb
        result = _gather_health(bot)
        assert "CIRCUIT BREAKER: OPEN" in result


class TestGatherStrategyHealth:
    def test_renders_without_crash(self, bot):
        result = _gather_strategy_health(bot)
        assert "Strategy Health" in result

    def test_with_journal_trade_stats(self, bot, tmp_path):
        """Verify the _get_connection fix (A2) works — previously crashed on _get_conn."""
        from kalshi_trader.journal import TradeJournal

        db_path = str(tmp_path / "test.db")
        journal = TradeJournal(db_path=db_path)
        journal.log_trade(
            market_ticker="TEST-MKT",
            side="no",
            action="buy",
            contracts=5,
            price_cents=90,
            order_id="test-001",
            reasoning="test",
            strategy="calibration_edge",
        )
        bot.journal = journal
        result = _gather_strategy_health(bot)
        assert "Total trades (all time): 1" in result
        assert "calibration_edge: 1 trades" in result


class TestGatherAllocation:
    def test_no_allocator(self, bot):
        result = _gather_allocation(bot)
        assert "not active" in result

    def test_no_plan_yet(self, bot):
        allocator = MagicMock()
        allocator.current_plan = None
        bot.capital_allocator = allocator
        result = _gather_allocation(bot)
        assert "cold start" in result


@pytest.mark.asyncio
async def test_gather_self_knowledge_no_crash(bot):
    """Full gather should never crash — graceful degradation on missing subsystems."""
    result = await gather_self_knowledge(bot)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "Portfolio State" in result
