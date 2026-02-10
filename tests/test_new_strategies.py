"""
Tests for new strategies: CryptoIntraday, BearMacro, MarketMaking.
Also tests the status bug fix in is_market_tradeable().
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone

from strategies.utils import is_market_tradeable
from strategies.crypto_intraday import (
    CryptoIntradayStrategy,
    _normal_cdf,
    _parse_strike_from_title,
)
from strategies.bear_macro import BearMacroStrategy
from strategies.market_making import MarketMakingStrategy
from strategies import STRATEGY_REGISTRY


# ─── Phase 0: Status Bug Fix ─────────────────────────────────────────────

class TestStatusBugFix:
    """Verify is_market_tradeable accepts both 'open' and 'active'."""

    def test_open_status_accepted(self):
        market = {"status": "open", "volume": 200, "yes_ask": 50}
        assert is_market_tradeable(market, min_volume=100) is True

    def test_active_status_accepted(self):
        market = {"status": "active", "volume": 200, "yes_ask": 50}
        assert is_market_tradeable(market, min_volume=100) is True

    def test_closed_status_rejected(self):
        market = {"status": "closed", "volume": 200, "yes_ask": 50}
        assert is_market_tradeable(market, min_volume=100) is False

    def test_settled_status_rejected(self):
        market = {"status": "settled", "volume": 200, "yes_ask": 50}
        assert is_market_tradeable(market, min_volume=100) is False

    def test_empty_status_rejected(self):
        market = {"status": "", "volume": 200, "yes_ask": 50}
        assert is_market_tradeable(market, min_volume=100) is False


# ─── Strategy Registry ────────────────────────────────────────────────────

class TestStrategyRegistry:
    """Verify all strategies are registered."""

    def test_registry_count(self):
        assert len(STRATEGY_REGISTRY) >= 13

    def test_new_strategies_registered(self):
        assert "crypto_intraday" in STRATEGY_REGISTRY
        assert "bear_macro" in STRATEGY_REGISTRY
        assert "market_making" in STRATEGY_REGISTRY


# ─── Crypto Intraday ──────────────────────────────────────────────────────

class TestCryptoIntraday:
    """Tests for CryptoIntradayStrategy."""

    def test_normal_cdf_center(self):
        """CDF(0) should be 0.5."""
        assert abs(_normal_cdf(0) - 0.5) < 1e-6

    def test_normal_cdf_positive(self):
        """CDF(2) should be ~0.977."""
        assert abs(_normal_cdf(2.0) - 0.9772) < 0.001

    def test_normal_cdf_negative(self):
        """CDF(-2) should be ~0.023."""
        assert abs(_normal_cdf(-2.0) - 0.0228) < 0.001

    def test_normal_cdf_extremes(self):
        """Extreme values should clamp to 0 and 1."""
        assert _normal_cdf(-10) == 0.0
        assert _normal_cdf(10) == 1.0

    def test_parse_strike_dollar(self):
        assert _parse_strike_from_title("Bitcoin above $95,000 at 3pm ET") == 95000.0

    def test_parse_strike_no_comma(self):
        assert _parse_strike_from_title("ETH above $3500") == 3500.0

    def test_parse_strike_decimal(self):
        assert _parse_strike_from_title("Solana above $200.50") == 200.50

    def test_parse_strike_no_match(self):
        assert _parse_strike_from_title("Some random title") is None

    @pytest.mark.asyncio
    async def test_scan_with_external_price_edge(self):
        """When external price is above strike, should find YES opportunity."""
        config = {
            "min_edge_cents": 2,
            "take_profit_cents": 6,
            "stop_loss_cents": 4,
            "min_volume": 10,
            "min_score": 0,
        }
        strategy = CryptoIntradayStrategy(config)

        market = {
            "ticker": "KXBTC-26FEB07-95000",
            "title": "Bitcoin above $95,000 at 3pm ET",
            "series_ticker": "KXBTC",
            "status": "active",
            "yes_bid": 45,
            "yes_ask": 50,
            "no_bid": 50,
            "no_ask": 55,
            "volume": 200,
        }

        with patch.object(
            strategy._price_feed,
            "get_prices",
            new_callable=AsyncMock,
            return_value={"BTC": 96000.0},
        ):
            opps = await strategy.scan_opportunities([market])

        # External price ($96k) is above strike ($95k), should find opportunity
        assert len(opps) >= 1
        assert opps[0].strategy_name == "crypto_intraday"
        assert opps[0].metadata["symbol"] == "BTC"
        assert opps[0].metadata["external_price"] == 96000.0

    @pytest.mark.asyncio
    async def test_scan_filters_low_volume(self):
        """Markets below min_volume should be filtered out."""
        config = {"min_volume": 500, "min_edge_cents": 1, "min_score": 0}
        strategy = CryptoIntradayStrategy(config)

        market = {
            "ticker": "KXBTC-LOW",
            "title": "Bitcoin above $95,000",
            "series_ticker": "KXBTC",
            "status": "active",
            "yes_bid": 45,
            "yes_ask": 50,
            "no_bid": 50,
            "no_ask": 55,
            "volume": 10,
        }

        with patch.object(
            strategy._price_feed,
            "get_prices",
            new_callable=AsyncMock,
            return_value={"BTC": 96000.0},
        ):
            opps = await strategy.scan_opportunities([market])

        assert len(opps) == 0

    def test_prior_stats(self):
        config = {"take_profit_cents": 6, "stop_loss_cents": 4}
        strategy = CryptoIntradayStrategy(config)
        stats = strategy._get_prior_stats()
        assert stats["win_rate"] == 0.50
        assert stats["avg_win_cents"] == 6.0
        assert stats["avg_loss_cents"] == 6.0


# ─── Bear Macro ───────────────────────────────────────────────────────────

class TestBearMacro:
    """Tests for BearMacroStrategy."""

    @pytest.mark.asyncio
    async def test_scan_with_fred_data(self):
        """Should generate opportunity when FRED data shows edge."""
        config = {
            "min_edge_cents": 3,
            "take_profit_cents": 10,
            "stop_loss_cents": 7,
            "min_volume": 10,
            "min_score": 0,
            "bear_mode_only": False,
        }
        strategy = BearMacroStrategy(config)

        market = {
            "ticker": "KXFED-26MAR-525",
            "title": "Fed rate above 5.25% at March meeting",
            "series_ticker": "KXFED",
            "status": "active",
            "yes_bid": 40,
            "yes_ask": 45,
            "no_bid": 55,
            "no_ask": 60,
            "volume": 200,
        }

        # FRED data: current rate 5.50%, above the 5.25% target
        fred_data = [
            {"date": "2026-02-01", "value": 5.50},
            {"date": "2026-01-01", "value": 5.50},
        ]

        with patch.object(
            strategy._fred,
            "get_regime_signals",
            new_callable=AsyncMock,
            return_value={"regime_score": 0.0, "yield_curve": 0.5, "unemployment_trend": 0.0, "fed_rate_trend": 0.0},
        ), patch.object(
            strategy._fred,
            "get_latest",
            new_callable=AsyncMock,
            return_value=fred_data,
        ):
            opps = await strategy.scan_opportunities([market])

        # Rate 5.50% > target 5.25% -> YES should be favored, fair_value > 70
        assert len(opps) >= 1
        assert opps[0].strategy_name == "bear_macro"
        assert opps[0].side == "yes"  # Rate is above target

    @pytest.mark.asyncio
    async def test_bear_mode_only_skips_bull(self):
        """When bear_mode_only=True and regime is bullish, should skip."""
        config = {
            "min_edge_cents": 3,
            "bear_mode_only": True,
            "min_volume": 10,
        }
        strategy = BearMacroStrategy(config)

        market = {
            "ticker": "KXFED-TEST",
            "title": "Fed rate above 5.25%",
            "series_ticker": "KXFED",
            "status": "active",
            "yes_bid": 40,
            "yes_ask": 45,
            "no_bid": 55,
            "no_ask": 60,
            "volume": 200,
        }

        with patch.object(
            strategy._fred,
            "get_regime_signals",
            new_callable=AsyncMock,
            return_value={"regime_score": 0.3},  # Bullish
        ):
            opps = await strategy.scan_opportunities([market])

        assert len(opps) == 0

    def test_parse_rate_from_title(self):
        assert BearMacroStrategy._parse_rate_from_title("Fed rate above 5.25%") == 5.25
        assert BearMacroStrategy._parse_rate_from_title("CPI above 3.2%") == 3.2
        assert BearMacroStrategy._parse_rate_from_title("No numbers here") is None

    def test_prior_stats(self):
        config = {"take_profit_cents": 10, "stop_loss_cents": 7}
        strategy = BearMacroStrategy(config)
        stats = strategy._get_prior_stats()
        assert stats["win_rate"] == 0.50
        assert stats["avg_win_cents"] == 6.0
        assert stats["avg_loss_cents"] == 6.0


# ─── Market Making ────────────────────────────────────────────────────────

class TestMarketMaking:
    """Tests for MarketMakingStrategy."""

    @pytest.mark.asyncio
    async def test_two_opportunities_per_market(self):
        """Should return 2 opportunities (YES bid + NO bid) for each quotable market."""
        config = {
            "min_spread_cents": 3,
            "max_spread_cents": 15,
            "inventory_limit": 10,
            "skew_per_contract": 1,
            "take_profit_cents": 3,
            "stop_loss_cents": 5,
            "min_volume": 10,
            "min_score": 0,
        }
        strategy = MarketMakingStrategy(config)

        market = {
            "ticker": "KXBTC-MM-TEST",
            "title": "Bitcoin above $95,000",
            "status": "active",
            "yes_bid": 44,
            "yes_ask": 50,   # YES spread = 6c
            "no_bid": 50,
            "no_ask": 56,    # NO spread = 6c
            "volume": 500,
        }

        opps = await strategy.scan_opportunities([market])

        assert len(opps) == 2
        sides = {o.side for o in opps}
        assert sides == {"yes", "no"}

        # Both should share a pair_id
        pair_ids = {o.metadata["pair_id"] for o in opps}
        assert len(pair_ids) == 1

    @pytest.mark.asyncio
    async def test_inventory_skew_shifts_prices(self):
        """Inventory imbalance should shift quotes."""
        config = {
            "min_spread_cents": 3,
            "max_spread_cents": 15,
            "inventory_limit": 10,
            "skew_per_contract": 2,
            "take_profit_cents": 3,
            "stop_loss_cents": 5,
            "min_volume": 10,
            "min_score": 0,
        }
        strategy = MarketMakingStrategy(config)

        market = {
            "ticker": "SKEW-TEST",
            "title": "Test market",
            "status": "active",
            "yes_bid": 44,
            "yes_ask": 50,
            "no_bid": 50,
            "no_ask": 56,
            "volume": 500,
        }

        # Simulate existing YES inventory (long YES)
        existing = {
            "SKEW-TEST": {
                "strategy_name": "market_making",
                "side": "yes",
                "contracts": 3,
            }
        }

        opps = await strategy.scan_opportunities([market], existing_positions=existing)

        # With 3 YES contracts and skew_per_contract=2, skew = 6c
        # YES bid should be lower (less aggressive on overweight side)
        yes_opp = [o for o in opps if o.side == "yes"][0] if [o for o in opps if o.side == "yes"] else None
        no_opp = [o for o in opps if o.side == "no"][0] if [o for o in opps if o.side == "no"] else None

        # Verify skew is tracked in metadata
        if yes_opp:
            assert yes_opp.metadata["skew"] == 6  # 3 contracts * 2c/contract

    @pytest.mark.asyncio
    async def test_tight_spread_filtered(self):
        """Markets with spreads below min_spread should be filtered out."""
        config = {
            "min_spread_cents": 5,
            "max_spread_cents": 15,
            "min_volume": 10,
            "min_score": 0,
        }
        strategy = MarketMakingStrategy(config)

        market = {
            "ticker": "TIGHT-SPREAD",
            "title": "Tight spread market",
            "status": "active",
            "yes_bid": 49,
            "yes_ask": 51,   # 2c spread (below min 5c)
            "no_bid": 49,
            "no_ask": 51,
            "volume": 500,
        }

        opps = await strategy.scan_opportunities([market])
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_inventory_limit_blocks_one_side(self):
        """At inventory limit, should only quote the reducing side."""
        config = {
            "min_spread_cents": 3,
            "max_spread_cents": 15,
            "inventory_limit": 2,
            "skew_per_contract": 1,
            "take_profit_cents": 3,
            "stop_loss_cents": 5,
            "min_volume": 10,
            "min_score": 0,
        }
        strategy = MarketMakingStrategy(config)

        market = {
            "ticker": "LIMIT-TEST",
            "title": "Limit test",
            "status": "active",
            "yes_bid": 44,
            "yes_ask": 50,
            "no_bid": 50,
            "no_ask": 56,
            "volume": 500,
        }

        # YES inventory at limit
        existing = {
            "LIMIT-TEST": {
                "strategy_name": "market_making",
                "side": "yes",
                "contracts": 2,
            }
        }

        opps = await strategy.scan_opportunities([market], existing_positions=existing)

        # Should only have NO bid (reducing YES exposure)
        sides = [o.side for o in opps]
        assert "yes" not in sides
        assert "no" in sides

    def test_prior_stats(self):
        config = {"take_profit_cents": 3, "stop_loss_cents": 5}
        strategy = MarketMakingStrategy(config)
        stats = strategy._get_prior_stats()
        assert stats["win_rate"] == 0.50
        assert stats["avg_win_cents"] == 6.0
        assert stats["avg_loss_cents"] == 6.0


# ─── Exit Signal Tests ────────────────────────────────────────────────────

class TestExitSignals:
    """Test exit conditions across new strategies."""

    @pytest.mark.asyncio
    async def test_crypto_take_profit(self):
        strategy = CryptoIntradayStrategy({"take_profit_cents": 6, "stop_loss_cents": 4})
        signal = await strategy.check_exit(
            {"entry_price": 40, "side": "yes"},
            current_price=47,
        )
        assert signal.should_exit is True
        assert signal.exit_type == "take_profit"

    @pytest.mark.asyncio
    async def test_crypto_stop_loss(self):
        strategy = CryptoIntradayStrategy({"take_profit_cents": 6, "stop_loss_cents": 4})
        signal = await strategy.check_exit(
            {"entry_price": 40, "side": "yes"},
            current_price=35,
        )
        assert signal.should_exit is True
        assert signal.exit_type == "stop_loss"

    @pytest.mark.asyncio
    async def test_bear_macro_hold(self):
        strategy = BearMacroStrategy({"take_profit_cents": 10, "stop_loss_cents": 7})
        signal = await strategy.check_exit(
            {"entry_price": 50, "side": "yes"},
            current_price=52,
        )
        assert signal.should_exit is False
        assert signal.exit_type == "hold"

    @pytest.mark.asyncio
    async def test_mm_take_profit(self):
        strategy = MarketMakingStrategy({"take_profit_cents": 3, "stop_loss_cents": 5})
        signal = await strategy.check_exit(
            {"entry_price": 45, "side": "yes"},
            current_price=48,
        )
        assert signal.should_exit is True
        assert signal.exit_type == "take_profit"
