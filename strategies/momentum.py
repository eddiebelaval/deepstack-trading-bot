"""
Momentum Strategy

Trend-following strategy based on price momentum.

Strategy logic:
- Track price changes over a lookback period
- Buy YES when price momentum is positive (price rising)
- Buy NO when price momentum is negative (price falling)
- Exit on momentum reversal or take profit/stop loss

This is a trend-following strategy that profits from continued price movement
in the same direction.

Expected Value Calculation (conservative):
- Win rate: 55% (trends continue more often than reverse)
- Avg win: 10 cents (let winners run)
- Avg loss: 6 cents (cut losers quickly)
- EV = (0.55 * 10) - (0.45 * 6) = 5.5 - 2.7 = +2.8 cents per contract
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal

logger = logging.getLogger(__name__)


class MomentumStrategy(Strategy):
    """
    Momentum/trend-following strategy for prediction markets.

    Identifies opportunities where price momentum indicates continued
    movement in the same direction.

    Configuration parameters:
        - lookback_periods: Number of price samples for momentum calc (default: 5)
        - momentum_threshold: Min momentum to trigger trade (default: 0.03 = 3%)
        - take_profit_cents: Target profit per contract (default: 10)
        - stop_loss_cents: Max loss per contract (default: 6)
        - min_volume: Minimum market volume (default: 200)
        - reversal_threshold: Momentum reversal to exit (default: 0.02)

    Example:
        >>> config = {"momentum_threshold": 0.05, "lookback_periods": 10}
        >>> strategy = MomentumStrategy(config)
        >>> opportunities = await strategy.scan_opportunities(markets)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize strategy with configuration.

        Args:
            config: Configuration dict with parameters
        """
        # Override defaults for momentum strategy
        config.setdefault("take_profit_cents", 10)
        config.setdefault("stop_loss_cents", 6)
        config.setdefault("min_volume", 200)

        super().__init__(config)

        self.lookback_periods = config.get("lookback_periods", 5)
        self.momentum_threshold = config.get("momentum_threshold", 0.03)
        self.reversal_threshold = config.get("reversal_threshold", 0.02)

        # Price history for momentum calculation
        # ticker -> [(timestamp, price), ...]
        self._price_history: Dict[str, List[tuple]] = defaultdict(list)
        self._max_history = 100  # Max samples to keep per ticker

        logger.info(
            f"MomentumStrategy initialized: "
            f"lookback={self.lookback_periods}, threshold={self.momentum_threshold:.1%}, "
            f"TP=+{self.take_profit}c, SL=-{self.stop_loss}c"
        )

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "momentum"

    @property
    def description(self) -> str:
        """Human-readable strategy description."""
        return (
            f"Momentum: Follow trends when price moves >{self.momentum_threshold:.0%} "
            f"over {self.lookback_periods} samples"
        )

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan markets for momentum opportunities.

        Updates price history and looks for significant momentum signals.

        Args:
            markets: List of market dictionaries from API
            existing_positions: Dict of ticker -> position (skip these)

        Returns:
            List of TradingOpportunity objects, sorted by score
        """
        existing_positions = existing_positions or {}
        opportunities = []
        now = datetime.now()

        for market in markets:
            ticker = market.get("ticker", "")
            status = market.get("status", "")
            volume = market.get("volume", 0) or market.get("volume_24h", 0)

            # Skip closed/settled markets
            if status != "open":
                continue

            # Skip low volume (momentum needs liquidity)
            if volume < self.min_volume:
                continue

            # Skip if already have position
            if ticker in existing_positions:
                continue

            # Get current price
            yes_bid = market.get("yes_bid", 0)
            yes_ask = market.get("yes_ask", 0)

            if yes_bid and yes_ask:
                current_price = (yes_bid + yes_ask) // 2
            else:
                current_price = market.get("last_price", 50)

            # Update price history
            self._update_price_history(ticker, current_price, now)

            # Calculate momentum
            momentum = self._calculate_momentum(ticker)

            if momentum is None:
                continue  # Not enough history

            # Check for momentum signal
            opp = self._analyze_momentum(
                ticker=ticker,
                title=market.get("title", ""),
                current_price=current_price,
                momentum=momentum,
                volume=volume,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=market.get("no_bid", 0),
                no_ask=market.get("no_ask", 0),
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

    def _update_price_history(
        self,
        ticker: str,
        price: int,
        timestamp: datetime,
    ) -> None:
        """Add price to history, maintaining max size."""
        history = self._price_history[ticker]
        history.append((timestamp, price))

        # Trim old entries
        if len(history) > self._max_history:
            self._price_history[ticker] = history[-self._max_history:]

    def _calculate_momentum(self, ticker: str) -> Optional[float]:
        """
        Calculate price momentum for a ticker.

        Returns:
            Momentum as percentage change, or None if insufficient data
        """
        history = self._price_history.get(ticker, [])

        if len(history) < self.lookback_periods:
            return None

        # Get prices from lookback period
        recent = history[-self.lookback_periods:]
        old_price = recent[0][1]
        new_price = recent[-1][1]

        if old_price == 0:
            return 0.0

        # Calculate percentage change
        return (new_price - old_price) / old_price

    def _analyze_momentum(
        self,
        ticker: str,
        title: str,
        current_price: int,
        momentum: float,
        volume: int,
        yes_bid: int,
        yes_ask: int,
        no_bid: int,
        no_ask: int,
    ) -> Optional[TradingOpportunity]:
        """
        Analyze momentum signal for trading opportunity.

        Returns:
            TradingOpportunity if strong momentum signal, None otherwise
        """
        abs_momentum = abs(momentum)

        # Check if momentum exceeds threshold
        if abs_momentum < self.momentum_threshold:
            return None

        # Determine direction
        if momentum > 0:
            # Price rising - buy YES
            side = "yes"
            entry_price = yes_ask if yes_ask else current_price
            reasoning = (
                f"Positive momentum: {momentum:+.1%} over {self.lookback_periods} samples. "
                f"Price at {current_price}c, expecting continued rise."
            )
        else:
            # Price falling - buy NO
            side = "no"
            entry_price = no_ask if no_ask else (100 - current_price)
            reasoning = (
                f"Negative momentum: {momentum:+.1%} over {self.lookback_periods} samples. "
                f"Price at {current_price}c, expecting continued fall."
            )

        # Calculate score
        # Higher momentum = better signal
        # Higher volume = more reliable
        momentum_score = min(abs_momentum / self.momentum_threshold, 3) * 30  # Max 90
        volume_score = min(volume / 2000, 1) * 30  # Max 30 for 2000+ volume
        spread_score = self._score_spread(yes_bid, yes_ask, no_bid, no_ask)

        total_score = momentum_score + volume_score + spread_score

        # Require minimum score
        if total_score < self.min_score:
            return None

        return TradingOpportunity(
            ticker=ticker,
            title=title,
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=current_price,
            current_no_price=100 - current_price,
            volume=volume,
            score=min(total_score, 100),  # Cap at 100
            reasoning=reasoning,
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "momentum": momentum,
                "lookback_periods": self.lookback_periods,
                "momentum_score": momentum_score,
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
        """Score the bid-ask spread (tighter is better)."""
        yes_spread = (yes_ask - yes_bid) if (yes_ask and yes_bid) else 10
        no_spread = (no_ask - no_bid) if (no_ask and no_bid) else 10

        avg_spread = (yes_spread + no_spread) / 2

        if avg_spread <= 1:
            return 20.0
        elif avg_spread >= 10:
            return 0.0
        else:
            return 20.0 * (1 - (avg_spread - 1) / 9)

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """
        Check if position should be exited.

        Exit conditions:
        1. Take profit: +10 cents (or configured amount)
        2. Stop loss: -6 cents (or configured amount)
        3. Momentum reversal: Momentum flips direction significantly
        4. Near expiry: Market closing soon

        Args:
            position: Position data with entry_price, side, ticker
            current_price: Current market price for our side
            market_data: Optional additional market data

        Returns:
            ExitSignal with recommendation
        """
        entry_price = position.get("entry_price", 50)
        side = position.get("side", "yes")
        ticker = position.get("ticker", "")

        # Calculate P&L
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

        # Check momentum reversal
        if ticker:
            # Update price history with current price
            self._update_price_history(ticker, current_price, datetime.now())
            momentum = self._calculate_momentum(ticker)

            if momentum is not None:
                # Check for reversal against our position
                if side == "yes" and momentum < -self.reversal_threshold:
                    return ExitSignal(
                        should_exit=True,
                        reason=f"Momentum reversal: {momentum:+.1%} (we're long YES)",
                        exit_type="manual",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.7,
                    )
                elif side == "no" and momentum > self.reversal_threshold:
                    return ExitSignal(
                        should_exit=True,
                        reason=f"Momentum reversal: {momentum:+.1%} (we're long NO)",
                        exit_type="manual",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.7,
                    )

        # Check near expiry
        if market_data:
            close_time_str = market_data.get("close_time")
            if close_time_str:
                try:
                    if isinstance(close_time_str, str):
                        close_time = datetime.fromisoformat(
                            close_time_str.replace("Z", "+00:00")
                        )
                    else:
                        close_time = close_time_str

                    time_to_close = (close_time - datetime.now(close_time.tzinfo)).total_seconds()
                    if 0 < time_to_close < 300:
                        return ExitSignal(
                            should_exit=True,
                            reason=f"Market closing in {int(time_to_close)}s",
                            exit_type="expiry",
                            current_price_cents=current_price,
                            pnl_cents=pnl_cents,
                            urgency=0.9,
                        )
                except (ValueError, TypeError):
                    pass

        # Hold position
        return ExitSignal(
            should_exit=False,
            reason=f"P&L: {pnl_cents:+d}c | Momentum: tracking",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def get_historical_stats(self) -> Dict[str, float]:
        """
        Get assumed historical statistics for Kelly calculation.

        Returns:
            Dict with win_rate, avg_win_cents, avg_loss_cents
        """
        # Momentum strategies have lower win rate but better risk/reward
        return {
            "win_rate": 0.55,
            "avg_win_cents": float(self.take_profit),  # 10c
            "avg_loss_cents": float(self.stop_loss),   # 6c
        }

    def validate_config(self) -> tuple[bool, str]:
        """Validate momentum-specific configuration."""
        valid, error = super().validate_config()
        if not valid:
            return valid, error

        if self.lookback_periods < 2:
            return False, "lookback_periods must be at least 2"

        if self.momentum_threshold <= 0:
            return False, "momentum_threshold must be positive"

        if self.reversal_threshold <= 0:
            return False, "reversal_threshold must be positive"

        return True, ""

    def clear_history(self, ticker: Optional[str] = None) -> None:
        """
        Clear price history.

        Args:
            ticker: Specific ticker to clear, or None for all
        """
        if ticker:
            self._price_history.pop(ticker, None)
        else:
            self._price_history.clear()
