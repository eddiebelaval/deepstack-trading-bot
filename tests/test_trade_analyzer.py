"""
Tests for TradeAnalyzer — Claude Intelligence Layer.

Covers:
- export_for_analysis() with mock trade data
- export with no trades returns empty structure
- export groups trades by strategy with per-strategy stats
- _build_user_message() produces valid markdown
- _parse_response() with well-formed JSON
- _parse_response() with markdown-fenced JSON
- _parse_response() with malformed JSON returns graceful fallback
- analyze() returns insufficient_data below min_trades threshold
- get_kelly_adjustments() extracts fractions when enabled
- get_kelly_adjustments() returns empty when disabled
- format_report() produces readable output
"""

import json
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from kalshi_trader.journal import TradeJournal
from kalshi_trader.trade_analyzer import (
    AnalysisResult,
    StrategyAssessment,
    TradeAnalyzer,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_journal.db")


@pytest.fixture
def journal(db_path):
    return TradeJournal(db_path)


@pytest.fixture
def journal_with_trades(journal):
    """Journal populated with a mix of winning and losing trades."""
    today = date.today()

    # Mean reversion trades (mostly winners)
    for i in range(8):
        tid = journal.log_trade(
            market_ticker=f"INXD-TEST-{i:03d}",
            side="yes",
            action="buy",
            contracts=10,
            price_cents=48,
            reasoning=f"Mean reversion: YES undervalued at 48c",
            strategy="mean_reversion",
        )
        # 6 winners, 2 losers
        if i < 6:
            journal.close_trade(tid, exit_price_cents=56, exit_reason="take_profit")
        else:
            journal.close_trade(tid, exit_price_cents=43, exit_reason="stop_loss")

    # Momentum trades (mostly losers)
    for i in range(5):
        tid = journal.log_trade(
            market_ticker=f"KXBTC-TEST-{i:03d}",
            side="yes",
            action="buy",
            contracts=5,
            price_cents=60,
            reasoning=f"Momentum breakout detected",
            strategy="momentum",
        )
        # 1 winner, 4 losers
        if i == 0:
            journal.close_trade(tid, exit_price_cents=70, exit_reason="take_profit")
        else:
            journal.close_trade(tid, exit_price_cents=54, exit_reason="stop_loss")

    return journal


@pytest.fixture
def analyzer():
    """TradeAnalyzer with default test config."""
    return TradeAnalyzer({
        "analysis": {
            "enabled": True,
            "model": "claude-sonnet-4-5-20250929",
            "auto_apply_kelly": True,
            "auto_apply_params": False,
            "min_trades_for_analysis": 10,
        }
    })


@pytest.fixture
def sample_analysis_response():
    """A well-formed Claude analysis response."""
    return json.dumps({
        "strategy_assessments": [
            {
                "strategy_name": "mean_reversion",
                "verdict": "healthy",
                "reasoning": "75% win rate is strong. Entry timing at 48c is good for mean reversion on INXD.",
                "kelly_suggestion": 0.25,
                "parameter_flags": [],
            },
            {
                "strategy_name": "momentum",
                "verdict": "no_edge",
                "reasoning": "20% win rate with -30c avg P&L. Momentum entries at 60c are chasing.",
                "kelly_suggestion": 0.0,
                "parameter_flags": [
                    {
                        "param": "momentum_threshold",
                        "current": 0.03,
                        "suggested": 0.05,
                        "reason": "Current threshold too low, catching noise",
                    }
                ],
            },
        ],
        "patterns_detected": [
            "Momentum losses cluster on crypto markets (KXBTC)",
            "Mean reversion consistent on INXD series",
        ],
        "risk_flags": [
            "Momentum strategy has negative expected value — disable or retune",
        ],
        "overall_summary": "Portfolio carried by mean reversion. Momentum is bleeding capital and should be disabled until parameters are adjusted.",
        "confidence": "high",
    })


# ── export_for_analysis tests ────────────────────────────────────────


class TestExportForAnalysis:
    def test_empty_journal_returns_empty_structure(self, journal):
        export = journal.export_for_analysis()
        assert export["trades"] == []
        assert export["by_strategy"] == {}
        assert export["summary"]["total_trades"] == 0

    def test_groups_trades_by_strategy(self, journal_with_trades):
        export = journal_with_trades.export_for_analysis()

        assert "mean_reversion" in export["by_strategy"]
        assert "momentum" in export["by_strategy"]

        mr = export["by_strategy"]["mean_reversion"]
        assert mr["stats"]["total_trades"] == 8
        assert mr["stats"]["winning_trades"] == 6
        assert mr["stats"]["losing_trades"] == 2

        mom = export["by_strategy"]["momentum"]
        assert mom["stats"]["total_trades"] == 5
        assert mom["stats"]["winning_trades"] == 1
        assert mom["stats"]["losing_trades"] == 4

    def test_includes_reasoning_and_exit_reason(self, journal_with_trades):
        export = journal_with_trades.export_for_analysis()
        trades = export["trades"]

        has_reasoning = any(t.get("reasoning") for t in trades)
        has_exit_reason = any(t.get("exit_reason") for t in trades)

        assert has_reasoning, "Trades should include reasoning field"
        assert has_exit_reason, "Trades should include exit_reason field"

    def test_summary_stats_are_correct(self, journal_with_trades):
        export = journal_with_trades.export_for_analysis()
        summary = export["summary"]

        assert summary["total_trades"] == 13
        assert summary["winning_trades"] == 7
        assert summary["losing_trades"] == 6

    def test_date_filtering(self, journal_with_trades):
        tomorrow = date.today() + timedelta(days=1)
        export = journal_with_trades.export_for_analysis(
            start_date=tomorrow,
            end_date=tomorrow,
        )
        assert export["trades"] == []

    def test_per_strategy_win_rate(self, journal_with_trades):
        export = journal_with_trades.export_for_analysis()

        mr_rate = export["by_strategy"]["mean_reversion"]["stats"]["win_rate"]
        assert mr_rate == 6 / 8  # 75%

        mom_rate = export["by_strategy"]["momentum"]["stats"]["win_rate"]
        assert mom_rate == 1 / 5  # 20%


# ── TradeAnalyzer prompt construction ────────────────────────────────


class TestPromptConstruction:
    def test_build_user_message_includes_strategy_sections(self, analyzer, journal_with_trades):
        export = journal_with_trades.export_for_analysis()
        config = {
            "strategies": [
                {"name": "mean_reversion", "enabled": True, "config": {"price_floor_cents": 45}},
            ],
            "risk": {"kelly_fraction": 0.5, "max_position_size": 50},
        }

        message = analyzer._build_user_message(export, config)

        assert "### Strategy: mean_reversion" in message
        assert "### Strategy: momentum" in message
        assert "### Portfolio Summary" in message
        assert "### Current Configuration" in message

    def test_build_user_message_includes_trade_table(self, analyzer, journal_with_trades):
        export = journal_with_trades.export_for_analysis()
        message = analyzer._build_user_message(export, {"strategies": [], "risk": {}})

        assert "| Ticker |" in message
        assert "INXD-TEST-" in message


# ── Response parsing ─────────────────────────────────────────────────


class TestResponseParsing:
    def test_parse_valid_json(self, analyzer, sample_analysis_response):
        result = analyzer._parse_response(sample_analysis_response)

        assert len(result.strategy_assessments) == 2
        assert result.strategy_assessments[0].strategy_name == "mean_reversion"
        assert result.strategy_assessments[0].verdict == "healthy"
        assert result.strategy_assessments[0].kelly_suggestion == 0.25
        assert result.strategy_assessments[1].verdict == "no_edge"
        assert result.confidence == "high"
        assert len(result.patterns_detected) == 2
        assert len(result.risk_flags) == 1

    def test_parse_markdown_fenced_json(self, analyzer, sample_analysis_response):
        fenced = f"```json\n{sample_analysis_response}\n```"
        result = analyzer._parse_response(fenced)

        assert len(result.strategy_assessments) == 2
        assert result.confidence == "high"

    def test_parse_malformed_json_returns_fallback(self, analyzer):
        result = analyzer._parse_response("this is not json {{{")

        assert result.confidence == "low"
        assert "Parse error" in result.overall_summary
        assert result.raw_response == "this is not json {{{"

    def test_parse_empty_response(self, analyzer):
        result = analyzer._parse_response("")

        assert result.confidence == "low"

    def test_parameter_flags_parsed(self, analyzer, sample_analysis_response):
        result = analyzer._parse_response(sample_analysis_response)

        momentum = result.strategy_assessments[1]
        assert len(momentum.parameter_flags) == 1
        assert momentum.parameter_flags[0]["param"] == "momentum_threshold"
        assert momentum.parameter_flags[0]["suggested"] == 0.05


# ── analyze() behavior ───────────────────────────────────────────────


class TestAnalyzeBehavior:
    @pytest.mark.asyncio
    async def test_insufficient_trades_returns_early(self, analyzer):
        export = {"summary": {"total_trades": 3}, "trades": [], "by_strategy": {}}
        result = await analyzer.analyze(export, {})

        assert "Insufficient data" in result.overall_summary
        assert result.confidence == "low"

    @pytest.mark.asyncio
    async def test_no_api_key_returns_unavailable(self):
        analyzer = TradeAnalyzer({"analysis": {"min_trades_for_analysis": 1}})
        # Ensure no API key
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            analyzer._api_key = ""
            export = {"summary": {"total_trades": 15}, "trades": [], "by_strategy": {}}
            result = await analyzer.analyze(export, {})

        assert "unavailable" in result.overall_summary.lower()


# ── Kelly adjustments ────────────────────────────────────────────────


class TestKellyAdjustments:
    def test_extracts_kelly_when_enabled(self, analyzer, sample_analysis_response):
        result = analyzer._parse_response(sample_analysis_response)
        adjustments = analyzer.get_kelly_adjustments(result)

        assert adjustments["mean_reversion"] == 0.25
        assert adjustments["momentum"] == 0.0

    def test_returns_empty_when_disabled(self, sample_analysis_response):
        analyzer = TradeAnalyzer({
            "analysis": {"auto_apply_kelly": False},
        })
        result = analyzer._parse_response(sample_analysis_response)
        adjustments = analyzer.get_kelly_adjustments(result)

        assert adjustments == {}


# ── Report formatting ────────────────────────────────────────────────


class TestFormatReport:
    def test_format_report_readable(self, analyzer, sample_analysis_response):
        result = analyzer._parse_response(sample_analysis_response)
        report = analyzer.format_report(result)

        assert "=== Trade Analysis Report ===" in report
        assert "[HEALTHY] mean_reversion" in report
        assert "[NO_EDGE] momentum" in report
        assert "Kelly suggestion: 0.25" in report
        assert "momentum_threshold" in report
        assert "Patterns Detected" in report
        assert "Risk Flags" in report
