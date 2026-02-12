"""
Tests for CommandProcessor — bounds validation, path traversal, error sanitization.

Covers:
- _handle_update_risk() bounds validation (kelly_fraction, max_position_size, daily_loss_limit)
- _handle_update_risk() valid params applied correctly
- _handle_place_trade() contracts cap enforcement
- _handle_switch_profile() path traversal rejection
- _sanitize_error() redacts paths, keys, and secrets
"""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kalshi_trader.command_processor import CommandProcessor


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_bot():
    """Minimal mock bot with config, risk, and client attributes."""
    bot = MagicMock()
    bot.config = SimpleNamespace(
        kelly_fraction=0.5,
        max_position_size=50.0,
        daily_loss_limit=100.0,
        poll_interval_seconds=60,
    )
    bot.risk = MagicMock()
    bot.risk.kelly_sizer = MagicMock()
    bot.risk.kelly_sizer.kelly_fraction = 0.5
    bot.risk.check_trade_allowed = MagicMock(return_value={"allowed": True, "reasons": []})
    bot.client = AsyncMock()
    bot.client.get_market = AsyncMock(return_value={"status": "open", "yes_ask": 50})
    bot.open_positions = {}
    bot.dry_run = True
    bot.strategy_manager = None
    bot.dashboard = None
    bot._paused = False
    bot._running = True
    return bot


@pytest.fixture
def processor(mock_bot):
    return CommandProcessor(mock_bot)


# ── Bounds validation tests ──────────────────────────────────────────


class TestUpdateRiskBounds:
    @pytest.mark.asyncio
    async def test_kelly_fraction_too_high_rejected(self, processor):
        result = await processor._handle_update_risk({"kelly_fraction": 5.0})
        assert "errors" in result
        assert any("kelly_fraction" in e for e in result["errors"])
        assert "kelly_fraction" not in result.get("updated", {})

    @pytest.mark.asyncio
    async def test_kelly_fraction_too_low_rejected(self, processor):
        result = await processor._handle_update_risk({"kelly_fraction": 0.01})
        assert "errors" in result
        assert any("kelly_fraction" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_max_position_size_too_high_rejected(self, processor):
        result = await processor._handle_update_risk({"max_position_size": 9999})
        assert "errors" in result
        assert any("max_position_size" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_daily_loss_limit_too_low_rejected(self, processor):
        result = await processor._handle_update_risk({"daily_loss_limit": 1})
        assert "errors" in result
        assert any("daily_loss_limit" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_valid_params_applied(self, processor, mock_bot):
        result = await processor._handle_update_risk({
            "kelly_fraction": 0.3,
            "max_position_size": 100,
            "daily_loss_limit": 200,
        })
        assert "errors" not in result
        assert result["updated"]["kelly_fraction"] == 0.3
        assert result["updated"]["max_position_size"] == 100
        assert result["updated"]["daily_loss_limit"] == 200
        assert mock_bot.config.kelly_fraction == 0.3
        assert mock_bot.config.max_position_size == 100
        assert mock_bot.config.daily_loss_limit == 200

    @pytest.mark.asyncio
    async def test_partial_valid_partial_invalid(self, processor):
        """Valid params should still be applied even if others fail."""
        result = await processor._handle_update_risk({
            "kelly_fraction": 0.4,
            "max_position_size": 99999,
        })
        assert result["updated"]["kelly_fraction"] == 0.4
        assert "max_position_size" not in result["updated"]
        assert "errors" in result


# ── Place trade bounds ───────────────────────────────────────────────


class TestPlaceTradeBounds:
    @pytest.mark.asyncio
    async def test_contracts_over_limit_rejected(self, processor):
        result = await processor._handle_place_trade({
            "ticker": "TEST-123",
            "side": "yes",
            "contracts": 50,
        })
        assert "error" in result
        assert "contracts" in result["error"]

    @pytest.mark.asyncio
    async def test_contracts_zero_rejected(self, processor):
        result = await processor._handle_place_trade({
            "ticker": "TEST-123",
            "side": "yes",
            "contracts": 0,
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_contracts_within_limit_passes(self, processor):
        result = await processor._handle_place_trade({
            "ticker": "TEST-123",
            "side": "yes",
            "contracts": 5,
        })
        # Should proceed to dry_run (not hit the contracts error)
        assert result.get("status") == "dry_run" or "error" not in result or "contracts" not in result.get("error", "")


# ── Path traversal ───────────────────────────────────────────────────


class TestSwitchProfilePathTraversal:
    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, processor):
        result = await processor._handle_switch_profile({
            "profile": "../../etc/passwd",
        })
        assert "error" in result
        assert "Invalid profile name" in result["error"]

    @pytest.mark.asyncio
    async def test_dotdot_in_name_rejected(self, processor):
        result = await processor._handle_switch_profile({
            "profile": "..%2f..%2fetc%2fpasswd",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_valid_profile_name_passes(self, processor):
        """Valid names should reach load_profile (which may return 'not found')."""
        result = await processor._handle_switch_profile({
            "profile": "aggressive",
        })
        # Should either succeed or return 'not found' — NOT 'Invalid profile name'
        assert "Invalid profile name" not in result.get("error", "")


# ── Error sanitization ───────────────────────────────────────────────


class TestErrorSanitization:
    def test_redacts_file_paths(self):
        error = Exception("Failed to read /Users/eddie/secrets/api_key.pem")
        sanitized = CommandProcessor._sanitize_error(error)
        assert "/Users/" not in sanitized
        assert "[REDACTED_PATH]" in sanitized

    def test_redacts_api_keys(self):
        error = Exception("Authentication failed: api_key=sk-abc123xyz token=abc")
        sanitized = CommandProcessor._sanitize_error(error)
        assert "sk-abc123xyz" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_truncates_long_errors(self):
        error = Exception("x" * 500)
        sanitized = CommandProcessor._sanitize_error(error)
        assert len(sanitized) <= 200

    def test_clean_error_passes_through(self):
        error = Exception("Market TEST-123 not found")
        sanitized = CommandProcessor._sanitize_error(error)
        assert "Market TEST-123 not found" in sanitized

    def test_redacts_home_paths(self):
        error = Exception("Config at /home/deploy/.config/bot.yaml failed")
        sanitized = CommandProcessor._sanitize_error(error)
        assert "/home/" not in sanitized
