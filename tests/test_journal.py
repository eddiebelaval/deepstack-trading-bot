"""
Tests for TradeJournal — the single source of truth for trade records.

Covers the critical settlement paths that were broken (A2, A7, A8 from audit).
"""

import os
import sqlite3
import tempfile
from datetime import date

import pytest

from kalshi_trader.journal import TradeJournal


@pytest.fixture
def journal(tmp_path):
    """Create a fresh journal with an in-memory-like temp file."""
    db_path = str(tmp_path / "test_journal.db")
    j = TradeJournal(db_path=db_path)
    return j


@pytest.fixture
def journal_with_trades(journal):
    """Journal pre-loaded with some open trades."""
    # 2 NO buys on same ticker (simulates multiple entries per market)
    journal.log_trade(
        market_ticker="KXBTC-26MAR-B70000",
        side="no",
        action="buy",
        contracts=5,
        price_cents=92,
        order_id="order-001",
        reasoning="Longshot overpriced",
        strategy="calibration_edge",
    )
    journal.log_trade(
        market_ticker="KXBTC-26MAR-B70000",
        side="no",
        action="buy",
        contracts=4,
        price_cents=90,
        order_id="order-002",
        reasoning="Longshot overpriced",
        strategy="calibration_edge",
    )
    # 1 YES buy on a different ticker
    journal.log_trade(
        market_ticker="KXCPI-26MAR-T0.3",
        side="yes",
        action="buy",
        contracts=3,
        price_cents=85,
        order_id="order-003",
        reasoning="CPI likely above 0.3",
        strategy="macro_edge",
    )
    return journal


class TestLogTrade:
    def test_log_trade_returns_id(self, journal):
        trade_id = journal.log_trade(
            market_ticker="TEST-MKT",
            side="yes",
            action="buy",
            contracts=1,
            price_cents=50,
            order_id="test-order",
            reasoning="test",
            strategy="test_strat",
        )
        assert trade_id is not None
        assert len(trade_id) > 0

    def test_log_trade_creates_open_entry(self, journal):
        journal.log_trade(
            market_ticker="TEST-MKT",
            side="no",
            action="buy",
            contracts=3,
            price_cents=88,
            order_id="test-order",
            reasoning="test",
            strategy="calibration_edge",
        )
        open_trades = journal.get_open_trades()
        assert len(open_trades) == 1
        assert open_trades[0]["market_ticker"] == "TEST-MKT"
        assert open_trades[0]["side"] == "no"
        assert open_trades[0]["contracts"] == 3
        assert open_trades[0]["entry_price_cents"] == 88
        assert open_trades[0]["status"] == "open"

    def test_log_paper_trade(self, journal):
        trade_id = journal.log_trade(
            market_ticker="TEST-MKT",
            side="yes",
            action="buy",
            contracts=10,
            price_cents=50,
            order_id="paper-abc123",
            reasoning="test",
            strategy="test_strat",
            is_paper=True,
            metadata={"paper_trade": True},
        )
        open_trades = journal.get_open_trades()
        assert len(open_trades) == 1
        assert open_trades[0]["is_paper"] == 1


class TestCloseTradesBySettlement:
    def test_no_result_closes_no_positions_pays_100(self, journal_with_trades):
        """NO result: NO buyers get 100c, YES buyers get 0c."""
        closed, pnl, contracts = journal_with_trades.close_trades_by_settlement(
            "KXBTC-26MAR-B70000", "no"
        )
        assert closed == 2
        assert contracts == 9  # 5 + 4

        # P&L = (100 - entry) * contracts - commission
        # Trade 1: (100 - 92) * 5 - 2*5 = 40 - 10 = 30
        # Trade 2: (100 - 90) * 4 - 2*4 = 40 - 8 = 32
        # Total = 62
        assert pnl == 62

    def test_yes_result_closes_no_positions_pays_0(self, journal_with_trades):
        """YES result: NO buyers get 0c (full loss)."""
        closed, pnl, contracts = journal_with_trades.close_trades_by_settlement(
            "KXBTC-26MAR-B70000", "yes"
        )
        assert closed == 2
        assert contracts == 9

        # P&L = (0 - entry) * contracts - commission
        # Trade 1: (0 - 92) * 5 - 10 = -460 - 10 = -470
        # Trade 2: (0 - 90) * 4 - 8 = -360 - 8 = -368
        # Total = -838
        assert pnl == -838

    def test_yes_result_closes_yes_positions_pays_100(self, journal_with_trades):
        """YES result: YES buyers get 100c."""
        closed, pnl, contracts = journal_with_trades.close_trades_by_settlement(
            "KXCPI-26MAR-T0.3", "yes"
        )
        assert closed == 1
        assert contracts == 3

        # P&L = (100 - 85) * 3 - 2*3 = 45 - 6 = 39
        assert pnl == 39

    def test_no_matching_ticker_returns_zero(self, journal_with_trades):
        closed, pnl, contracts = journal_with_trades.close_trades_by_settlement(
            "NONEXISTENT-MKT", "yes"
        )
        assert closed == 0
        assert pnl == 0
        assert contracts == 0

    def test_idempotent_second_call_returns_zero(self, journal_with_trades):
        """Second call on same ticker should be a no-op."""
        journal_with_trades.close_trades_by_settlement("KXBTC-26MAR-B70000", "no")
        closed, pnl, contracts = journal_with_trades.close_trades_by_settlement(
            "KXBTC-26MAR-B70000", "no"
        )
        assert closed == 0
        assert pnl == 0

    def test_settlement_sets_status_closed(self, journal_with_trades):
        journal_with_trades.close_trades_by_settlement("KXBTC-26MAR-B70000", "no")
        open_trades = journal_with_trades.get_open_trades()
        # Only the CPI trade should remain open
        assert len(open_trades) == 1
        assert open_trades[0]["market_ticker"] == "KXCPI-26MAR-T0.3"

    def test_commission_deducted_from_pnl(self, journal):
        """Verify entry commission (2c/contract) is deducted (A8 fix)."""
        journal.log_trade(
            market_ticker="COMM-TEST",
            side="no",
            action="buy",
            contracts=10,
            price_cents=90,
            order_id="order-comm",
            reasoning="test",
            strategy="test",
        )
        closed, pnl, contracts = journal.close_trades_by_settlement(
            "COMM-TEST", "no"
        )
        # Without commission: (100-90)*10 = 100
        # With commission: 100 - 2*10 = 80
        assert pnl == 80
        assert contracts == 10

    def test_void_result(self, journal_with_trades):
        """Void market result — Kalshi refunds the entry, so P&L is zero.

        The old behavior settled voids at 0c, booking a refund as a total
        loss and corrupting win rate / Kelly / circuit-breaker inputs.
        """
        closed, pnl, contracts = journal_with_trades.close_trades_by_settlement(
            "KXBTC-26MAR-B70000", "void"
        )
        assert closed == 2
        assert pnl == 0


class TestGetOpenTrades:
    def test_returns_only_open(self, journal_with_trades):
        open_trades = journal_with_trades.get_open_trades()
        assert len(open_trades) == 3
        for t in open_trades:
            assert t["status"] == "open"

    def test_empty_journal(self, journal):
        assert journal.get_open_trades() == []


class TestGetDailyPnl:
    def test_no_trades_returns_zero(self, journal):
        assert journal.get_daily_pnl() == 0

    def test_settled_trades_counted(self, journal_with_trades):
        journal_with_trades.close_trades_by_settlement("KXBTC-26MAR-B70000", "no")
        pnl = journal_with_trades.get_daily_pnl(date.today())
        assert pnl == 62  # Same as settlement P&L

    def test_open_trades_not_counted(self, journal_with_trades):
        # Don't close anything — P&L should be 0
        assert journal_with_trades.get_daily_pnl() == 0


class TestCloseTrade:
    def test_close_trade_records_exit(self, journal):
        trade_id = journal.log_trade(
            market_ticker="EXIT-TEST",
            side="yes",
            action="buy",
            contracts=5,
            price_cents=60,
            order_id="order-exit",
            reasoning="test",
            strategy="test",
        )
        pnl = journal.close_trade(
            trade_id=trade_id,
            exit_price_cents=75,
            exit_order_id="exit-order-001",
            exit_reason="take_profit",
        )
        # close_trade computes net P&L with commissions
        # Gross: (75-60)*5 = 75. Entry comm: 2*5=10. Exit comm: 2*5=10. Net: 55.
        assert pnl == 55

        open_trades = journal.get_open_trades()
        assert len(open_trades) == 0
