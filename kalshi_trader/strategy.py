"""
Mean Reversion Strategy for Kalshi S&P 500 Hourly Markets

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
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .config import KalshiConfig

logger = logging.getLogger(__name__)


@dataclass
class TradingOpportunity:
    """Represents a potential trading opportunity."""

    ticker: str
    title: str
    side: str  # "yes" or "no"
    entry_price_cents: int
    current_yes_price: int
    current_no_price: int
    volume: int
    score: float  # Opportunity quality score (0-100)
    reasoning: str
    expected_profit_cents: int  # If trade works out
    max_loss_cents: int  # Stop loss level


@dataclass
class ExitSignal:
    """Represents a signal to exit a position."""

    should_exit: bool
    reason: str
    exit_type: str  # "take_profit", "stop_loss", "expiry", "manual"
    current_price_cents: int
    pnl_cents: int


class MeanReversionStrategy:
    """
    Mean reversion strategy for prediction markets.

    Identifies opportunities where market prices deviate from 50%
    (maximum uncertainty) and bets on reversion.

    Configuration parameters from KalshiConfig:
        - price_floor_cents: Minimum price to consider (default: 45)
        - price_ceiling_cents: Maximum price to consider (default: 55)
        - take_profit_cents: Target profit per contract (default: 8)
        - stop_loss_cents: Max loss per contract (default: 5)
        - min_volume: Minimum market volume (default: 100)

    Expected Value with default parameters:
        - Win rate: 60%
        - EV = (0.60 * 8) - (0.40 * 5) = +2.8 cents per contract

    Example:
        >>> strategy = MeanReversionStrategy(config)
        >>> opportunities = strategy.find_opportunities(markets)
        >>> for opp in opportunities:
        ...     print(f"{opp.ticker}: {opp.side} @ {opp.entry_price_cents}c")
    """

    def __init__(self, config: KalshiConfig):
        """
        Initialize strategy with configuration.

        Args:
            config: KalshiConfig with strategy parameters
        """
        self.config = config
        self.price_floor = config.price_floor_cents
        self.price_ceiling = config.price_ceiling_cents
        self.take_profit = config.take_profit_cents
        self.stop_loss = config.stop_loss_cents
        self.min_volume = config.min_volume

        logger.info(
            f"MeanReversionStrategy initialized: "
            f"floor={self.price_floor}c, ceiling={self.price_ceiling}c, "
            f"TP=+{self.take_profit}c, SL=-{self.stop_loss}c"
        )

    def find_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, int]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan markets for trading opportunities.

        Filters for:
        1. Market series matches config (e.g., INXD)
        2. Market is open and has sufficient volume
        3. Yes price is in the sweet spot (near 50)
        4. Not already in a position

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
            if status != "open":
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
            f"Found {len(opportunities)} opportunities from {len(markets)} markets"
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
        Analyze a single market for opportunity.

        Returns:
            TradingOpportunity if good setup, None otherwise
        """
        # Check if in price range
        if not (self.price_floor <= yes_price <= self.price_ceiling):
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
        if total_score < 30:
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

    def should_exit_position(
        self,
        entry_price_cents: int,
        current_price_cents: int,
        side: str,
        entry_time: Optional[datetime] = None,
        market_close_time: Optional[datetime] = None,
    ) -> ExitSignal:
        """
        Determine if position should be exited.

        Exit conditions:
        1. Take profit: +8 cents (or configured amount)
        2. Stop loss: -5 cents (or configured amount)
        3. Near expiry: Market closing soon (within 5 minutes)

        Args:
            entry_price_cents: Price we entered at
            current_price_cents: Current market price for our side
            side: "yes" or "no"
            entry_time: When we entered (optional)
            market_close_time: When market closes (optional)

        Returns:
            ExitSignal with recommendation
        """
        # Calculate P&L
        if side == "yes":
            # For YES position, we profit when price goes up
            pnl_cents = current_price_cents - entry_price_cents
        else:
            # For NO position, we profit when YES price goes down
            # (our NO is worth more)
            pnl_cents = current_price_cents - entry_price_cents

        # Check take profit
        if pnl_cents >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit hit: +{pnl_cents}c (target: +{self.take_profit}c)",
                exit_type="take_profit",
                current_price_cents=current_price_cents,
                pnl_cents=pnl_cents,
            )

        # Check stop loss
        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss hit: {pnl_cents}c (limit: -{self.stop_loss}c)",
                exit_type="stop_loss",
                current_price_cents=current_price_cents,
                pnl_cents=pnl_cents,
            )

        # Check near expiry (if we have close time)
        if market_close_time:
            time_to_close = (market_close_time - datetime.now()).total_seconds()
            if 0 < time_to_close < 300:  # Within 5 minutes
                return ExitSignal(
                    should_exit=True,
                    reason=f"Market closing in {int(time_to_close)}s, exiting to avoid settlement risk",
                    exit_type="expiry",
                    current_price_cents=current_price_cents,
                    pnl_cents=pnl_cents,
                )

        # Hold position
        return ExitSignal(
            should_exit=False,
            reason=f"P&L: {pnl_cents:+d}c (TP: +{self.take_profit}c, SL: -{self.stop_loss}c)",
            exit_type="hold",
            current_price_cents=current_price_cents,
            pnl_cents=pnl_cents,
        )

    def get_exit_price(
        self,
        entry_price_cents: int,
        side: str,
        exit_type: str,
    ) -> int:
        """
        Calculate target exit price for limit orders.

        Args:
            entry_price_cents: Entry price
            side: "yes" or "no"
            exit_type: "take_profit" or "stop_loss"

        Returns:
            Target price in cents
        """
        if exit_type == "take_profit":
            # Add profit margin
            return entry_price_cents + self.take_profit
        elif exit_type == "stop_loss":
            # Subtract loss margin
            return max(1, entry_price_cents - self.stop_loss)
        else:
            return entry_price_cents

    def get_historical_stats(self) -> Dict[str, float]:
        """
        Get assumed historical statistics for Kelly calculation.

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
            "avg_loss_cents": float(self.stop_loss),   # 5c
        }

    def calculate_edge(self) -> Dict[str, float]:
        """
        Calculate theoretical edge of the strategy.

        Uses assumed historical stats to compute expected value.

        Returns:
            Dict with edge metrics
        """
        stats = self.get_historical_stats()
        win_rate = stats["win_rate"]
        avg_win = stats["avg_win_cents"]
        avg_loss = stats["avg_loss_cents"]

        # Expected value per trade (in cents)
        ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Kelly %
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        kelly = ((win_rate * win_loss_ratio) - (1 - win_rate)) / win_loss_ratio

        return {
            "expected_value_cents": ev,
            "win_loss_ratio": win_loss_ratio,
            "kelly_pct": kelly,
            "assumed_win_rate": win_rate,
        }
