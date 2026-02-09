"""
Mean Reversion Strategy

Strategy logic:
- Target markets with prices near 50 cents (high uncertainty)
- Buy YES when price < 50 (market undervaluing probability)
- Buy NO when price > 50 (market overvaluing probability)
- Take profit at +8 cents (adjusted for positive EV)
- Stop loss at -5 cents (tighter stop for better risk:reward)

This is a contrarian strategy based on the assumption that near-50
markets have high uncertainty and tend to mean-revert.

Expected Value Calculation:
- Win rate: 60% (conservative for mean-reversion)
- Avg win: 8 cents (take profit)
- Avg loss: 5 cents (stop loss)
- EV = (0.60 * 8) - (0.40 * 5) = 4.8 - 2.0 = +2.8 cents per contract
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal

logger = logging.getLogger(__name__)


class MeanReversionStrategy(Strategy):
    """
    Mean reversion strategy for prediction markets.

    Identifies opportunities where market prices deviate from 50%
    (maximum uncertainty) and bets on reversion.

    Configuration parameters:
        - price_floor_cents: Minimum price to consider (default: 45)
        - price_ceiling_cents: Maximum price to consider (default: 55)
        - take_profit_cents: Target profit per contract (default: 8)
        - stop_loss_cents: Max loss per contract (default: 5)
        - min_volume: Minimum market volume (default: 100)

    Expected Value with default parameters:
        - Win rate: 60%
        - EV = (0.60 * 8) - (0.40 * 5) = +2.8 cents per contract

    Example:
        >>> config = {"price_floor_cents": 45, "price_ceiling_cents": 55}
        >>> strategy = MeanReversionStrategy(config)
        >>> opportunities = await strategy.scan_opportunities(markets)
        >>> for opp in opportunities:
        ...     print(f"{opp.ticker}: {opp.side} @ {opp.entry_price_cents}c")
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize strategy with configuration.

        Args:
            config: Configuration dict with parameters:
                - price_floor_cents: Min price (default 45)
                - price_ceiling_cents: Max price (default 55)
                - take_profit_cents: Take profit (default 8)
                - stop_loss_cents: Stop loss (default 5)
                - min_volume: Min volume (default 100)
        """
        super().__init__(config)

        self.price_floor = config.get("price_floor_cents", 45)
        self.price_ceiling = config.get("price_ceiling_cents", 55)

        logger.info(
            f"MeanReversionStrategy initialized: "
            f"floor={self.price_floor}c, ceiling={self.price_ceiling}c, "
            f"TP=+{self.take_profit}c, SL=-{self.stop_loss}c"
        )

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "mean_reversion"

    @property
    def description(self) -> str:
        """Human-readable strategy description."""
        return (
            f"Mean reversion: Buy when price deviates from 50c "
            f"(range: {self.price_floor}-{self.price_ceiling}c)"
        )

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan markets for mean-reversion opportunities.

        Filters for:
        1. Market is open and has sufficient volume
        2. Yes price is in the sweet spot (near 50)
        3. Not already in a position

        Args:
            markets: List of market dictionaries from API
            existing_positions: Dict of ticker -> position (skip these)

        Returns:
            List of TradingOpportunity objects, sorted by score
        """
        existing_positions = existing_positions or {}
        opportunities = []

        for market in markets:
            ticker = market.get("ticker", "")
            status = market.get("status", "")
            volume = market.get("volume", 0) or market.get("volume_24h", 0)

            # Skip closed/settled markets
            if status not in ("open", "active"):
                continue

            # Skip low volume
            if volume < self.min_volume:
                continue

            # Skip if already have position
            if ticker in existing_positions:
                continue

            # Get prices
            yes_bid = market.get("yes_bid", 0)
            yes_ask = market.get("yes_ask", 0)
            no_bid = market.get("no_bid", 0)
            no_ask = market.get("no_ask", 0)

            # Calculate mid price (or use last price)
            if yes_bid and yes_ask:
                yes_mid = (yes_bid + yes_ask) // 2
            else:
                yes_mid = market.get("last_price", 50)

            # Analyze opportunity
            opp = self._analyze_market(
                ticker=ticker,
                title=market.get("title", ""),
                yes_price=yes_mid,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=no_bid,
                no_ask=no_ask,
                volume=volume,
            )

            if opp:
                opportunities.append(opp)

        # Sort by score (best first)
        opportunities.sort(key=lambda x: x.score, reverse=True)

        logger.info(
            f"[{self.name}] Found {len(opportunities)} opportunities "
            f"from {len(markets)} markets"
        )

        return opportunities

    def _analyze_market(
        self,
        ticker: str,
        title: str,
        yes_price: int,
        yes_bid: int,
        yes_ask: int,
        no_bid: int,
        no_ask: int,
        volume: int,
    ) -> Optional[TradingOpportunity]:
        """
        Analyze a single market for mean-reversion opportunity.

        Returns:
            TradingOpportunity if good setup, None otherwise
        """
        # Check if in price range
        if not (self.price_floor <= yes_price <= self.price_ceiling):
            return None

        # Reject wide spreads — if the spread exceeds our take profit,
        # the edge is eaten by execution cost even if the thesis is correct
        yes_spread = (yes_ask - yes_bid) if (yes_ask and yes_bid) else 99
        no_spread = (no_ask - no_bid) if (no_ask and no_bid) else 99
        max_acceptable_spread = self.take_profit * 2  # Spread can't exceed 2x our TP
        if min(yes_spread, no_spread) > max_acceptable_spread:
            return None

        # Determine side based on deviation from 50
        if yes_price < 50:
            # Market undervalues YES - buy YES
            side = "yes"
            entry_price = yes_ask if yes_ask else yes_price
            reasoning = f"YES undervalued at {yes_price}c (below 50), expect reversion up"
            deviation = 50 - yes_price
        else:
            # Market overvalues YES - buy NO
            side = "no"
            entry_price = no_ask if no_ask else (100 - yes_price)
            reasoning = f"YES overvalued at {yes_price}c (above 50), buy NO for reversion"
            deviation = yes_price - 50

        # Calculate opportunity score
        # Higher deviation from 50 = better opportunity
        # Higher volume = more reliable signal
        deviation_score = deviation / 10 * 40  # Max 20 points for 5c deviation
        volume_score = min(volume / 1000, 1) * 30  # Max 30 points for 1000+ volume
        spread_score = self._score_spread(yes_bid, yes_ask, no_bid, no_ask)

        total_score = deviation_score + volume_score + spread_score

        # Require minimum score
        if total_score < self.min_score:
            return None

        return TradingOpportunity(
            ticker=ticker,
            title=title,
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=yes_price,
            current_no_price=100 - yes_price,
            volume=volume,
            score=total_score,
            reasoning=reasoning,
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "deviation": deviation,
                "deviation_score": deviation_score,
                "volume_score": volume_score,
                "spread_score": spread_score,
            },
        )

    def _score_spread(
        self,
        yes_bid: int,
        yes_ask: int,
        no_bid: int,
        no_ask: int,
    ) -> float:
        """
        Score the bid-ask spread (tighter is better).

        Returns:
            Score from 0-30 based on spread quality
        """
        # Calculate spreads
        yes_spread = (yes_ask - yes_bid) if (yes_ask and yes_bid) else 10
        no_spread = (no_ask - no_bid) if (no_ask and no_bid) else 10

        avg_spread = (yes_spread + no_spread) / 2

        # Score: 1c spread = 30 points, 10c spread = 0 points
        if avg_spread <= 1:
            return 30.0
        elif avg_spread >= 10:
            return 0.0
        else:
            return 30.0 * (1 - (avg_spread - 1) / 9)

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """
        Determine if position should be exited.

        Exit conditions:
        1. Take profit: +8 cents (or configured amount)
        2. Stop loss: -5 cents (or configured amount)
        3. Near expiry: Market closing soon (within 5 minutes)

        Args:
            position: Position data with entry_price, side, entry_time
            current_price: Current market price for our side
            market_data: Optional additional market data

        Returns:
            ExitSignal with recommendation
        """
        entry_price = position.get("entry_price", 50)
        side = position.get("side", "yes")
        entry_time = position.get("entry_time")

        # Calculate P&L
        # For both YES and NO positions, we profit when our side's price goes up
        pnl_cents = current_price - entry_price

        # Check take profit
        if pnl_cents >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit hit: +{pnl_cents}c (target: +{self.take_profit}c)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        # Check stop loss
        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss hit: {pnl_cents}c (limit: -{self.stop_loss}c)",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        # Check near expiry (if we have market data with close time)
        if market_data:
            close_time_str = market_data.get("close_time")
            if close_time_str:
                try:
                    # Parse close time (assuming ISO format)
                    if isinstance(close_time_str, str):
                        close_time = datetime.fromisoformat(
                            close_time_str.replace("Z", "+00:00")
                        )
                    else:
                        close_time = close_time_str

                    time_to_close = (close_time - datetime.now(close_time.tzinfo)).total_seconds()
                    if 0 < time_to_close < 300:  # Within 5 minutes
                        return ExitSignal(
                            should_exit=True,
                            reason=f"Market closing in {int(time_to_close)}s, exiting to avoid settlement risk",
                            exit_type="expiry",
                            current_price_cents=current_price,
                            pnl_cents=pnl_cents,
                            urgency=0.9,
                        )
                except (ValueError, TypeError):
                    pass  # Ignore parse errors

        # Hold position
        return ExitSignal(
            should_exit=False,
            reason=f"P&L: {pnl_cents:+d}c (TP: +{self.take_profit}c, SL: -{self.stop_loss}c)",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """
        Get hardcoded prior statistics for Kelly calculation.

        These are tuned for positive expected value with the
        8c take profit / 5c stop loss configuration.

        Returns:
            Dict with win_rate, avg_win_cents, avg_loss_cents
        """
        # Optimized for positive EV:
        # EV = (0.60 * 8) - (0.40 * 5) = 4.8 - 2.0 = +2.8c per contract
        return {
            "win_rate": 0.60,  # 60% win rate for mean reversion
            "avg_win_cents": float(self.take_profit),  # 8c
            "avg_loss_cents": float(self.stop_loss),  # 5c
        }

    def validate_config(self) -> tuple[bool, str]:
        """Validate mean-reversion specific configuration."""
        valid, error = super().validate_config()
        if not valid:
            return valid, error

        if self.price_ceiling <= self.price_floor:
            return False, f"price_ceiling ({self.price_ceiling}) must be > price_floor ({self.price_floor})"

        if self.price_floor < 1 or self.price_ceiling > 99:
            return False, "price_floor and price_ceiling must be between 1 and 99"

        return True, ""
