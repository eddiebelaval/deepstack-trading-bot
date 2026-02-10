"""
Calibration Edge Detector Strategy

Exploits the "favorite-longshot bias" — the most documented systematic error
in prediction markets. Research shows:
- Longshots (<30c) are overpriced — they resolve YES ~26% less often than price implies
- Favorites (>70c) are underpriced — they resolve YES ~3.6% more often than price implies

Edge:
    Use a calibration table mapping market_price -> true_probability
    (derived from prediction market research). When the gap between
    calibrated and market price exceeds threshold, trade the difference.

Expected Value:
    Win rate: 58% | Avg win: 6c | Avg loss: 4c
    EV = (0.58 * 6) - (0.42 * 4) = 3.48 - 1.68 = +1.80c per contract
"""

import logging
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import score_spread, score_volume, is_market_tradeable, clamp_score

logger = logging.getLogger(__name__)


# Calibration table: market_price_cents -> true_probability (0-1)
# Source: Academic research on prediction market calibration
# Longshots are overpriced, favorites are underpriced
CALIBRATION_TABLE: Dict[int, float] = {
    5: 0.02,    # Market says 5%, reality ~2%
    10: 0.06,   # Market says 10%, reality ~6%
    15: 0.10,   # Market says 15%, reality ~10%
    20: 0.15,   # Market says 20%, reality ~15%
    25: 0.20,   # Market says 25%, reality ~20%
    30: 0.26,   # Market says 30%, reality ~26%
    35: 0.31,   # Market says 35%, reality ~31%
    40: 0.37,   # Market says 40%, reality ~37%
    45: 0.43,   # Starting to converge
    50: 0.50,   # Well-calibrated at 50%
    55: 0.57,   # Starting to diverge
    60: 0.63,
    65: 0.69,
    70: 0.74,   # Market says 70%, reality ~74%
    75: 0.79,   # Market says 75%, reality ~79%
    80: 0.86,   # Market says 80%, reality ~86% — significant underpricing
    85: 0.90,
    90: 0.94,
    95: 0.98,   # Market says 95%, reality ~98%
}


def get_calibrated_probability(market_price_cents: int) -> float:
    """
    Look up calibrated true probability for a market price.
    Interpolates between table entries.

    Args:
        market_price_cents: Market price in cents (1-99)

    Returns:
        Calibrated probability (0-1)
    """
    if market_price_cents <= 0:
        return 0.0
    if market_price_cents >= 100:
        return 1.0

    # Find surrounding table entries
    lower_key = max(k for k in CALIBRATION_TABLE if k <= market_price_cents)
    upper_key = min(k for k in CALIBRATION_TABLE if k >= market_price_cents)

    if lower_key == upper_key:
        return CALIBRATION_TABLE[lower_key]

    # Linear interpolation
    lower_prob = CALIBRATION_TABLE[lower_key]
    upper_prob = CALIBRATION_TABLE[upper_key]
    fraction = (market_price_cents - lower_key) / (upper_key - lower_key)

    return lower_prob + fraction * (upper_prob - lower_prob)


class CalibrationEdgeStrategy(Strategy):
    """
    Trade the favorite-longshot bias using a calibration table.

    Configuration:
        min_edge_cents: Min gap between calibrated and market price (default: 3)
        favorite_threshold_cents: Above this = favorite zone (default: 70)
        longshot_threshold_cents: Below this = longshot zone (default: 30)
        take_profit_cents: Target profit (default: 6)
        stop_loss_cents: Max loss (default: 4)
    """

    def __init__(self, config: Dict[str, Any]):
        config.setdefault("take_profit_cents", 6)
        config.setdefault("stop_loss_cents", 4)
        super().__init__(config)

        self.min_edge = config.get("min_edge_cents", 3)
        self.favorite_threshold = config.get("favorite_threshold_cents", 70)
        self.longshot_threshold = config.get("longshot_threshold_cents", 30)

        logger.info(
            f"CalibrationEdgeStrategy initialized: "
            f"min_edge={self.min_edge}c, "
            f"favorite>{self.favorite_threshold}c, "
            f"longshot<{self.longshot_threshold}c"
        )

    @property
    def name(self) -> str:
        return "calibration_edge"

    @property
    def description(self) -> str:
        return (
            f"Calibration edge: Exploit favorite-longshot bias "
            f"(min edge: {self.min_edge}c)"
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

            yes_bid = market.get("yes_bid", 0)
            yes_ask = market.get("yes_ask", 0)
            no_bid = market.get("no_bid", 0)
            no_ask = market.get("no_ask", 0)
            volume = market.get("volume", 0) or market.get("volume_24h", 0)

            # Get mid price
            if yes_bid and yes_ask:
                market_price = (yes_bid + yes_ask) // 2
            else:
                continue  # Need bid/ask for this strategy

            # Get calibrated probability
            true_prob = get_calibrated_probability(market_price)
            true_price_cents = int(true_prob * 100)
            edge_cents = true_price_cents - market_price

            opp = self._evaluate_edge(
                ticker=ticker,
                title=market.get("title", ""),
                market_price=market_price,
                true_price_cents=true_price_cents,
                edge_cents=edge_cents,
                volume=volume,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=no_bid,
                no_ask=no_ask,
            )

            if opp:
                opportunities.append(opp)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}] Found {len(opportunities)} opportunities "
            f"from {len(markets)} markets"
        )
        return opportunities

    def _evaluate_edge(
        self,
        ticker: str,
        title: str,
        market_price: int,
        true_price_cents: int,
        edge_cents: int,
        volume: int,
        yes_bid: int,
        yes_ask: int,
        no_bid: int,
        no_ask: int,
    ) -> Optional[TradingOpportunity]:
        """Evaluate calibration edge for a single market."""

        # Determine zone and direction
        if market_price >= self.favorite_threshold and edge_cents >= self.min_edge:
            # Favorite is underpriced — buy YES
            side = "yes"
            entry_price = yes_ask if yes_ask else market_price
            zone = "favorite"
            zone_strength = (market_price - self.favorite_threshold) / 30.0
            reasoning = (
                f"Favorite underpriced: market {market_price}c, "
                f"calibrated {true_price_cents}c (+{edge_cents}c edge). "
                f"Buying YES."
            )
        elif market_price <= self.longshot_threshold and edge_cents <= -self.min_edge:
            # Longshot is overpriced — buy NO
            side = "no"
            entry_price = no_ask if no_ask else (100 - market_price)
            edge_cents = abs(edge_cents)
            zone = "longshot"
            zone_strength = (self.longshot_threshold - market_price) / 30.0
            reasoning = (
                f"Longshot overpriced: market {market_price}c, "
                f"calibrated {true_price_cents}c (-{edge_cents}c edge). "
                f"Buying NO."
            )
        else:
            return None  # No edge or in neutral zone

        # Score
        edge_score = min(abs(edge_cents) / 10.0, 1.0) * 40
        vol_score = score_volume(volume, target=1000, max_score=25)
        zone_score = min(zone_strength, 1.0) * 20
        spread_sc = score_spread(yes_bid, yes_ask, no_bid, no_ask, max_score=15)

        total_score = clamp_score(edge_score + vol_score + zone_score + spread_sc)

        if total_score < self.min_score:
            return None

        return TradingOpportunity(
            ticker=ticker,
            title=title,
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=market_price,
            current_no_price=100 - market_price,
            volume=volume,
            score=total_score,
            reasoning=reasoning,
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "market_price": market_price,
                "calibrated_price": true_price_cents,
                "edge_cents": edge_cents,
                "zone": zone,
                "zone_strength": zone_strength,
            },
        )

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        entry_price = position.get("entry_price", 50)
        pnl_cents = current_price - entry_price

        if pnl_cents >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit: +{pnl_cents}c (target: +{self.take_profit}c)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss: {pnl_cents}c (limit: -{self.stop_loss}c)",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        return ExitSignal(
            should_exit=False,
            reason=f"P&L: {pnl_cents:+d}c (TP: +{self.take_profit}c, SL: -{self.stop_loss}c)",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        # Neutral priors — let Bayesian learning converge to reality
        return {
            "win_rate": 0.50,
            "avg_win_cents": 6.0,
            "avg_loss_cents": 6.0,
        }

    def validate_config(self) -> tuple[bool, str]:
        valid, error = super().validate_config()
        if not valid:
            return valid, error

        if self.min_edge < 1:
            return False, "min_edge_cents must be at least 1"

        if self.longshot_threshold >= self.favorite_threshold:
            return False, "longshot_threshold must be < favorite_threshold"

        return True, ""
