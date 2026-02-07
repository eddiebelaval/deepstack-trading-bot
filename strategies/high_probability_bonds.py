"""
High Probability Bonds Strategy

Buy contracts priced 93-98c that are near-certain to resolve YES.
Collect the remaining 2-7 cents as "bond coupon" yield.

Edge:
    Markets at 93-98c are extremely likely to resolve YES.
    The 2-7c remaining is essentially risk-free yield, similar to
    buying a bond near maturity at a slight discount.

Risk:
    Asymmetric loss — if the "certain" outcome fails, you lose 93-98c
    to earn 2-7c. Kelly Criterion naturally sizes these very small.

Expected Value:
    Win rate: 97% | Avg win: 4c | Avg loss: 95c
    EV = (0.97 * 4) - (0.03 * 95) = 3.88 - 2.85 = +1.03c per contract
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import score_spread, score_volume, hours_until_close, is_market_tradeable, clamp_score

logger = logging.getLogger(__name__)


class HighProbabilityBondsStrategy(Strategy):
    """
    Buy near-certain YES contracts and hold to settlement.

    Configuration:
        min_probability_cents: Min YES price to consider (default: 93)
        max_probability_cents: Max YES price — avoid 99c, no edge (default: 98)
        min_volume: Minimum market volume (default: 500)
        max_hours_to_expiry: Max hours until settlement (default: 72)
        stop_loss_cents: Exit if price drops this much (default: 8)
        take_profit_cents: Sell at 99c or hold to settlement (default: 2)
    """

    def __init__(self, config: Dict[str, Any]):
        config.setdefault("take_profit_cents", 2)
        config.setdefault("stop_loss_cents", 8)
        config.setdefault("min_volume", 500)
        super().__init__(config)

        self.min_prob = config.get("min_probability_cents", 93)
        self.max_prob = config.get("max_probability_cents", 98)
        self.max_hours = config.get("max_hours_to_expiry", 72)

        logger.info(
            f"HighProbabilityBondsStrategy initialized: "
            f"range={self.min_prob}-{self.max_prob}c, "
            f"max_hours={self.max_hours}, "
            f"SL=-{self.stop_loss}c"
        )

    @property
    def name(self) -> str:
        return "high_probability_bonds"

    @property
    def description(self) -> str:
        return (
            f"High-probability bonds: Buy YES at {self.min_prob}-{self.max_prob}c, "
            f"hold to settlement for {100 - self.max_prob}-{100 - self.min_prob}c yield"
        )

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        existing_positions = existing_positions or {}
        opportunities = []

        for market in markets:
            ticker = market.get("ticker", "")

            if not is_market_tradeable(market, self.min_volume):
                continue

            if ticker in existing_positions:
                continue

            # Check time to expiry
            hours = hours_until_close(market)
            if hours is not None and hours > self.max_hours:
                continue

            yes_ask = market.get("yes_ask", 0)
            yes_bid = market.get("yes_bid", 0)
            no_bid = market.get("no_bid", 0)
            no_ask = market.get("no_ask", 0)
            volume = market.get("volume", 0) or market.get("volume_24h", 0)

            if not (self.min_prob <= yes_ask <= self.max_prob):
                continue

            # Score the opportunity
            expected_profit = 100 - yes_ask  # Profit if settles YES
            max_loss = yes_ask  # Loss if settles NO

            # Probability confidence: higher price = more confident
            prob_score = ((yes_ask - self.min_prob) / max(1, self.max_prob - self.min_prob)) * 35

            # Time to expiry: closer = better (more certain)
            if hours is not None and hours > 0:
                time_score = max(0, 30 * (1 - hours / self.max_hours))
            else:
                time_score = 15  # Unknown time, moderate score

            vol_score = score_volume(volume, target=2000, max_score=20)
            spread_sc = score_spread(yes_bid, yes_ask, no_bid, no_ask, max_score=15)

            total_score = clamp_score(prob_score + time_score + vol_score + spread_sc)

            if total_score < self.min_score:
                continue

            opportunities.append(
                TradingOpportunity(
                    ticker=ticker,
                    title=market.get("title", ""),
                    side="yes",
                    entry_price_cents=yes_ask,
                    current_yes_price=yes_bid or yes_ask,
                    current_no_price=no_bid or (100 - yes_ask),
                    volume=volume,
                    score=total_score,
                    reasoning=(
                        f"High-prob bond: YES at {yes_ask}c, expected yield {expected_profit}c. "
                        f"{'Expires in ' + f'{hours:.0f}h' if hours else 'Unknown expiry'}."
                    ),
                    expected_profit_cents=expected_profit,
                    max_loss_cents=max_loss,
                    strategy_name=self.name,
                    metadata={
                        "prob_score": prob_score,
                        "time_score": time_score,
                        "hours_to_expiry": hours,
                    },
                )
            )

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}] Found {len(opportunities)} opportunities "
            f"from {len(markets)} markets"
        )
        return opportunities

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        entry_price = position.get("entry_price", 95)
        pnl_cents = current_price - entry_price

        # Take profit at 99c
        if current_price >= 99:
            return ExitSignal(
                should_exit=True,
                reason=f"Price at 99c, taking profit: +{pnl_cents}c",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.6,
            )

        # Stop loss: thesis broken — price dropped significantly
        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=(
                    f"Stop loss: price dropped to {current_price}c "
                    f"({pnl_cents}c from entry). Thesis may be broken."
                ),
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        # Near expiry: hold — this is the strategy (settle at 100)
        if market_data:
            hours = hours_until_close(market_data)
            if hours is not None and hours < 1 and current_price >= 90:
                return ExitSignal(
                    should_exit=False,
                    reason=f"Near settlement ({hours:.1f}h), holding for 100c resolution",
                    exit_type="hold",
                    current_price_cents=current_price,
                    pnl_cents=pnl_cents,
                    urgency=0.0,
                )

        return ExitSignal(
            should_exit=False,
            reason=f"Holding bond: P&L {pnl_cents:+d}c, current {current_price}c",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        return {
            "win_rate": 0.97,
            "avg_win_cents": 4.0,
            "avg_loss_cents": 95.0,
        }

    def validate_config(self) -> tuple[bool, str]:
        valid, error = super().validate_config()
        if not valid:
            return valid, error

        if self.min_prob < 80:
            return False, "min_probability_cents should be >= 80 for this strategy"

        if self.max_prob >= 99:
            return False, "max_probability_cents must be < 99 (no edge at 99c)"

        if self.min_prob >= self.max_prob:
            return False, "min_probability_cents must be < max_probability_cents"

        if self.max_hours <= 0:
            return False, "max_hours_to_expiry must be positive"

        return True, ""
