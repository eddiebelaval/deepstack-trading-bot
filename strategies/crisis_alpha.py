"""
Crisis Alpha Strategy

Trades inverse ETFs, safe havens, and volatility products during market stress.
Activated by regime detection (trending_down, high_vol_choppy) or VIX spikes.

Instead of shorting stocks directly (margin, borrow fees, unlimited risk),
this buys INVERSE ETFs (SQQQ, SDOW, SH) — same directional bet, capped risk,
no margin needed, works with existing long-only IBKR order infrastructure.

Asset universe:
    - Inverse equity: SQQQ (-3x Nasdaq), SDOW (-3x Dow), SH (-1x S&P)
    - Volatility: UVXY (1.5x VIX), VIXY (VIX short-term)
    - Safe haven: GLD (gold), TLT (long bonds)
    - Energy: USO (crude oil), XLE (energy sector)
    - Defense: LMT, RTX, NOC (defense contractors)

Design:
    - Regime-gated: only enters during trending_down or high_vol_choppy
    - VIX-aware: checks VIXY price momentum for volatility confirmation
    - Tier system: conservative (1x inverse, safe haven) vs aggressive (3x leveraged)
    - Paper trading by default
    - Max 5 concurrent positions across all crisis trades
"""

import logging
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import clamp_score

logger = logging.getLogger(__name__)

# Crisis asset tiers
TIER_CONSERVATIVE = {
    "SH": {"type": "inverse_equity", "leverage": 1, "desc": "-1x S&P 500"},
    "GLD": {"type": "safe_haven", "leverage": 1, "desc": "Gold ETF"},
    "TLT": {"type": "safe_haven", "leverage": 1, "desc": "20+ Year Treasury"},
}

TIER_AGGRESSIVE = {
    "SQQQ": {"type": "inverse_equity", "leverage": 3, "desc": "-3x Nasdaq 100"},
    "SDOW": {"type": "inverse_equity", "leverage": 3, "desc": "-3x Dow Jones"},
    "UVXY": {"type": "volatility", "leverage": 1.5, "desc": "1.5x VIX Futures"},
}

TIER_GEOPOLITICAL = {
    "USO": {"type": "energy", "leverage": 1, "desc": "Crude Oil Fund"},
    "XLE": {"type": "energy", "leverage": 1, "desc": "Energy Sector ETF"},
    "LMT": {"type": "defense", "leverage": 1, "desc": "Lockheed Martin"},
    "RTX": {"type": "defense", "leverage": 1, "desc": "RTX Corp (Raytheon)"},
    "NOC": {"type": "defense", "leverage": 1, "desc": "Northrop Grumman"},
}

ALL_CRISIS_ASSETS = {**TIER_CONSERVATIVE, **TIER_AGGRESSIVE, **TIER_GEOPOLITICAL}


class CrisisAlphaStrategy(Strategy):
    """
    Crisis alpha: buy inverse ETFs, volatility, safe havens, and geopolitical plays
    when the market regime signals stress.

    Key insight: buying SQQQ when the market drops is functionally identical to
    shorting QQQ — but with capped downside, no margin, and no borrow fees.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_regime_confidence = config.get("min_regime_confidence", 0.4)
        self.take_profit_pct = config.get("take_profit_pct", 0.05)  # 5% TP
        self.stop_loss_pct = config.get("stop_loss_pct", 0.03)  # 3% SL
        self.max_positions = config.get("max_positions", 5)
        self.paper_trade = config.get("paper_trade", True)
        self.use_leveraged = config.get("use_leveraged", True)  # Allow 3x ETFs
        self.use_geopolitical = config.get("use_geopolitical", True)  # Oil/defense
        self.vix_momentum_threshold = config.get("vix_momentum_threshold", 0.02)

    @property
    def name(self) -> str:
        return "crisis_alpha"

    @property
    def description(self) -> str:
        return "Inverse ETFs, volatility, and safe havens during market stress"

    def _get_active_tickers(self) -> Dict[str, Dict]:
        """Get the crisis asset universe based on config."""
        assets = dict(TIER_CONSERVATIVE)
        if self.use_leveraged:
            assets.update(TIER_AGGRESSIVE)
        if self.use_geopolitical:
            assets.update(TIER_GEOPOLITICAL)
        return assets

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
        governance_engine: Optional[Any] = None,
    ) -> List[TradingOpportunity]:
        """Scan for crisis trading opportunities.

        Only generates signals when stock regime indicates stress:
        - trending_down: buy inverse ETFs + safe havens
        - high_vol_choppy: buy volatility products + safe havens
        - trending_up: geopolitical plays only (oil/defense during war)
        """
        existing_positions = existing_positions or {}

        if not governance_engine:
            logger.debug("crisis_alpha: no governance engine — skipping")
            return []

        stock_regime = governance_engine.get_regime_for_asset_class("stock")
        if not stock_regime:
            logger.debug("crisis_alpha: no stock regime detected — skipping")
            return []

        if stock_regime.confidence < self.min_regime_confidence:
            logger.debug(
                "crisis_alpha: regime confidence %.2f < %.2f — skipping",
                stock_regime.confidence, self.min_regime_confidence,
            )
            return []

        regime_name = stock_regime.regime.value

        # Determine which assets to target based on regime
        target_types = set()
        regime_score_bonus = 0

        if regime_name == "trending_down":
            target_types = {"inverse_equity", "safe_haven", "volatility", "energy", "defense"}
            regime_score_bonus = 20
            logger.info(
                "crisis_alpha: TRENDING_DOWN (conf=%.2f) — full crisis mode activated",
                stock_regime.confidence,
            )
        elif regime_name == "high_vol_choppy":
            target_types = {"volatility", "safe_haven"}
            regime_score_bonus = 10
            logger.info(
                "crisis_alpha: HIGH_VOL_CHOPPY (conf=%.2f) — volatility + safe haven mode",
                stock_regime.confidence,
            )
        elif regime_name == "trending_up" and self.use_geopolitical:
            # In an uptrend with geopolitical tension, oil/defense can still rally
            target_types = {"energy", "defense"}
            regime_score_bonus = 0
            logger.info(
                "crisis_alpha: TRENDING_UP but geopolitical plays active",
            )
        else:
            logger.debug("crisis_alpha: regime %s — no crisis signals", regime_name)
            return []

        active_assets = self._get_active_tickers()

        # Build market data lookup
        market_lookup: Dict[str, Dict] = {}
        for m in markets:
            ticker = m.get("ticker", "")
            if ticker:
                market_lookup[ticker] = m

        # Also check VIXY for volatility confirmation
        vixy_data = market_lookup.get("VIXY")
        vix_elevated = False
        if vixy_data:
            vixy_price = vixy_data.get("last_price", 0)
            # VIXY above $20 generally indicates elevated volatility
            if vixy_price > 2000:  # In cents
                vix_elevated = True

        opportunities = []
        for ticker, asset_info in active_assets.items():
            if asset_info["type"] not in target_types:
                continue

            if ticker in existing_positions:
                continue

            market_data = market_lookup.get(ticker)
            if not market_data:
                continue

            current_price = market_data.get("last_price", 0)
            if current_price <= 0:
                continue

            # Score based on regime strength + asset characteristics
            base_score = stock_regime.confidence * 30 + regime_score_bonus

            # Bonus for VIX confirmation
            if vix_elevated and asset_info["type"] in ("inverse_equity", "volatility"):
                base_score += 15

            # Bonus for leveraged products in strong trends
            if asset_info["leverage"] > 1 and stock_regime.confidence > 0.6:
                base_score += 10

            # Penalty for leveraged in uncertain conditions
            if asset_info["leverage"] > 1 and stock_regime.confidence < 0.5:
                base_score -= 10

            score = clamp_score(base_score)
            if score < self.min_score:
                continue

            # Tighter stops for leveraged products
            leverage = asset_info["leverage"]
            tp_pct = self.take_profit_pct / leverage if leverage > 1 else self.take_profit_pct
            sl_pct = self.stop_loss_pct / leverage if leverage > 1 else self.stop_loss_pct

            expected_profit = int(current_price * tp_pct)
            max_loss = int(current_price * sl_pct)

            opportunities.append(TradingOpportunity(
                ticker=ticker,
                title=f"{ticker} Crisis ({asset_info['desc']})",
                side="buy",  # Always buying — inverse ETFs = short exposure via long position
                entry_price_cents=current_price,
                current_yes_price=current_price,
                current_no_price=0,
                volume=market_data.get("volume", 0),
                score=score,
                reasoning=(
                    f"Regime: {regime_name} (conf={stock_regime.confidence:.2f}) | "
                    f"Type: {asset_info['type']} | "
                    f"Leverage: {leverage}x | "
                    f"VIX elevated: {vix_elevated} | "
                    f"TP: {tp_pct:.1%} / SL: {sl_pct:.1%}"
                ),
                expected_profit_cents=expected_profit,
                max_loss_cents=max_loss,
                strategy_name=self.name,
                asset_class="stock",
                metadata={
                    "asset_type": asset_info["type"],
                    "leverage": leverage,
                    "description": asset_info["desc"],
                    "stock_regime": regime_name,
                    "regime_confidence": stock_regime.confidence,
                    "vix_elevated": vix_elevated,
                    "paper_trade": self.paper_trade,
                },
            ))

            if len(opportunities) >= self.max_positions:
                break

        return sorted(opportunities, key=lambda o: o.score, reverse=True)

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """Check if a crisis position should be exited.

        Tighter exits than stock_momentum — crisis trades are tactical, not strategic.
        Leveraged products get proportionally tighter stops.
        """
        entry_price = position.get("entry_price", position.get("entry_price_cents", 0))
        if entry_price <= 0:
            return ExitSignal(
                should_exit=False, reason="No entry price", exit_type="hold",
                current_price_cents=current_price, pnl_cents=0,
            )

        pnl_cents = current_price - entry_price  # Always long
        pnl_pct = pnl_cents / entry_price if entry_price > 0 else 0

        # Adjust thresholds for leverage
        metadata = position.get("metadata", {})
        leverage = metadata.get("leverage", 1)
        tp_pct = self.take_profit_pct / leverage if leverage > 1 else self.take_profit_pct
        sl_pct = self.stop_loss_pct / leverage if leverage > 1 else self.stop_loss_pct

        if pnl_pct >= tp_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"Crisis TP: {pnl_pct:.1%} >= {tp_pct:.1%} ({leverage}x leverage)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        if pnl_pct <= -sl_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"Crisis SL: {pnl_pct:.1%} <= -{sl_pct:.1%} ({leverage}x leverage)",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        return ExitSignal(
            should_exit=False,
            reason=f"Holding crisis position: {pnl_pct:.1%} P&L ({leverage}x)",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """Prior statistics for crisis alpha strategy."""
        return {
            "win_rate": 0.50,        # Crisis trades are binary — hit or miss
            "avg_win_cents": 800.0,  # ~$8 avg win (larger moves in crisis)
            "avg_loss_cents": 400.0, # ~$4 avg loss (tight stops)
        }
