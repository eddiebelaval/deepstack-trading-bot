"""
Cross-Platform Arbitrage Strategy

Compares prices between Polymarket and Kalshi to identify mispricings.
Uses Polymarket as a data/intelligence source and executes trades on Kalshi.

Strategy Logic:
    1. Fetch markets from both Polymarket and Kalshi
    2. Match equivalent markets using fuzzy title/topic matching
    3. Compare YES prices across platforms
    4. Flag opportunities where price difference > threshold
    5. Generate signals: buy Kalshi if underpriced vs Polymarket, sell if overpriced
    6. Use Polymarket volume/momentum as confirmation signal

Key Insight:
    Polymarket is one of the most liquid prediction markets globally. When
    Polymarket and Kalshi prices diverge significantly, the Polymarket price
    is often more accurate (due to higher liquidity/volume). We can exploit
    Kalshi mispricings by using Polymarket as a "price oracle."

Example Workflow:
    1. Scan Polymarket: "Trump wins 2024" = 55c
    2. Find Kalshi equivalent: "GOP wins presidency" = 48c
    3. 7c discrepancy > 5c threshold
    4. Generate signal: BUY Kalshi "GOP wins" (underpriced vs Polymarket)
    5. Execute trade on Kalshi only

Configuration (config.yaml):
    ```yaml
    config:
        price_diff_threshold_cents: 5  # Minimum price diff to trigger
        min_match_score: 0.6           # Minimum market match confidence
        min_polymarket_volume: 10000   # Min Polymarket 24h volume
        min_kalshi_volume: 100         # Min Kalshi volume
        use_volume_confirmation: true  # Require Polymarket volume momentum
        volume_momentum_threshold: 1.5 # 50% volume increase signals momentum
    ```

Risk Considerations:
    - Markets may not be perfectly equivalent (different resolution criteria)
    - Price convergence isn't guaranteed (different user bases)
    - Execution timing matters (prices can move during analysis)
    - Match accuracy affects signal quality
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .base import Strategy, TradingOpportunity, ExitSignal

# Import Polymarket client for type hints
try:
    from markets.polymarket import PolymarketMarket, MatchedMarketPair, MarketMatcher
except ImportError:
    PolymarketMarket = None
    MatchedMarketPair = None
    MarketMatcher = None

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CrossPlatformSignal:
    """
    A cross-platform arbitrage signal.

    Attributes:
        polymarket_ticker: Polymarket market ID
        kalshi_ticker: Kalshi market ticker
        polymarket_title: Polymarket market title
        kalshi_title: Kalshi market title
        polymarket_price: Polymarket YES price (cents)
        kalshi_price: Kalshi YES price (cents)
        price_diff_cents: Difference (Kalshi - Polymarket)
        match_score: How well markets match (0-1)
        signal_type: "buy" or "sell" on Kalshi
        confidence: Signal confidence (0-1)
        reasoning: Explanation of the signal
        polymarket_volume: Polymarket 24h volume
        kalshi_volume: Kalshi volume
        volume_momentum: Polymarket volume trend (ratio)
    """

    polymarket_ticker: str
    kalshi_ticker: str
    polymarket_title: str
    kalshi_title: str
    polymarket_price: int
    kalshi_price: int
    price_diff_cents: int
    match_score: float
    signal_type: str  # "buy" or "sell"
    confidence: float
    reasoning: str
    polymarket_volume: int = 0
    kalshi_volume: int = 0
    volume_momentum: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Cross-Platform Arbitrage Strategy
# =============================================================================


class CrossPlatformArbitrageStrategy(Strategy):
    """
    Cross-platform arbitrage strategy using Polymarket as price oracle.

    Compares prices between Polymarket and Kalshi for equivalent markets.
    When Kalshi is underpriced vs Polymarket, generates buy signal.
    When Kalshi is overpriced vs Polymarket, generates sell signal.

    Polymarket is READ-ONLY - all trades execute on Kalshi.

    Configuration Parameters:
        - price_diff_threshold_cents: Min price diff to trigger (default: 5)
        - min_match_score: Min market match confidence (default: 0.6)
        - min_polymarket_volume: Min Polymarket 24h volume (default: 10000)
        - min_kalshi_volume: Min Kalshi volume (default: 100)
        - use_volume_confirmation: Use Polymarket volume as signal (default: true)
        - volume_momentum_threshold: Volume increase ratio (default: 1.5)
        - take_profit_cents: Profit target (default: 5)
        - stop_loss_cents: Loss limit (default: 3)

    Example:
        >>> config = {"price_diff_threshold_cents": 5}
        >>> strategy = CrossPlatformArbitrageStrategy(config)
        >>> strategy.set_market_clients(kalshi_client, polymarket_client)
        >>> opportunities = await strategy.scan_opportunities(kalshi_markets)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize cross-platform arbitrage strategy.

        Args:
            config: Configuration dictionary with strategy parameters
        """
        super().__init__(config)

        # Strategy-specific parameters
        self.price_diff_threshold = config.get("price_diff_threshold_cents", 5)
        self.min_match_score = config.get("min_match_score", 0.6)
        self.min_polymarket_volume = config.get("min_polymarket_volume", 10000)
        self.min_kalshi_volume = config.get("min_kalshi_volume", 100)
        self.use_volume_confirmation = config.get("use_volume_confirmation", True)
        self.volume_momentum_threshold = config.get("volume_momentum_threshold", 1.5)

        # Market clients (set externally)
        self._kalshi_client = None
        self._polymarket_client: Optional[PolymarketMarket] = None

        # Market matcher (create own if Polymarket client not provided)
        self._matcher: Optional[MarketMatcher] = None

        # Cache for matched pairs
        self._matched_pairs: Dict[str, MatchedMarketPair] = {}

        # Volume history for momentum calculation
        self._volume_history: Dict[str, List[Tuple[datetime, int]]] = {}

        # Active signals tracking
        self._active_signals: Dict[str, CrossPlatformSignal] = {}

        logger.info(
            f"CrossPlatformArbitrageStrategy initialized: "
            f"price_diff_threshold={self.price_diff_threshold}c, "
            f"min_match_score={self.min_match_score}, "
            f"min_polymarket_volume={self.min_polymarket_volume}"
        )

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "cross_platform_arbitrage"

    @property
    def description(self) -> str:
        """Human-readable strategy description."""
        return (
            f"Cross-platform arbitrage: Compare Polymarket vs Kalshi prices, "
            f"buy/sell when diff > {self.price_diff_threshold}c"
        )

    def set_market_clients(
        self,
        kalshi_client: Any,
        polymarket_client: Optional[Any] = None,
    ) -> None:
        """
        Set market clients for data fetching.

        Args:
            kalshi_client: Kalshi market client
            polymarket_client: Optional Polymarket client (creates one if not provided)
        """
        self._kalshi_client = kalshi_client

        if polymarket_client:
            self._polymarket_client = polymarket_client
            self._matcher = polymarket_client.matcher
        else:
            # Create Polymarket client if not provided
            if PolymarketMarket:
                self._polymarket_client = PolymarketMarket({
                    "min_match_score": self.min_match_score,
                })
                self._matcher = self._polymarket_client.matcher

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan for cross-platform arbitrage opportunities.

        Process:
        1. Use provided markets as Kalshi data
        2. Fetch Polymarket markets
        3. Match markets across platforms
        4. Identify price discrepancies
        5. Apply filters (volume, match quality)
        6. Generate trading signals for Kalshi

        Args:
            markets: Kalshi market data (from orchestrator)
            existing_positions: Dict of ticker -> position to exclude

        Returns:
            List of TradingOpportunity for Kalshi execution
        """
        existing_positions = existing_positions or {}
        opportunities = []

        # Ensure Polymarket client is available
        if not self._polymarket_client:
            logger.warning("Polymarket client not configured, skipping cross-platform scan")
            return []

        try:
            # Fetch Polymarket markets
            await self._polymarket_client.connect()
            polymarket_markets = await self._polymarket_client.get_open_markets(limit=200)

            logger.info(
                f"[{self.name}] Fetched {len(polymarket_markets)} Polymarket markets, "
                f"comparing with {len(markets)} Kalshi markets"
            )

            # Find cross-platform signals
            signals = self._find_cross_platform_signals(
                kalshi_markets=markets,
                polymarket_markets=polymarket_markets,
            )

            logger.info(f"[{self.name}] Found {len(signals)} potential signals")

            # Convert signals to TradingOpportunity
            for signal in signals:
                # Skip if we already have a position
                if signal.kalshi_ticker in existing_positions:
                    continue

                opp = self._signal_to_opportunity(signal)
                if opp:
                    opportunities.append(opp)
                    self._active_signals[signal.kalshi_ticker] = signal

            # Sort by confidence
            opportunities.sort(key=lambda x: x.score, reverse=True)

            logger.info(
                f"[{self.name}] Generated {len(opportunities)} trading opportunities"
            )

            return opportunities

        except Exception as e:
            logger.error(f"[{self.name}] Error scanning opportunities: {e}")
            return []

    def _find_cross_platform_signals(
        self,
        kalshi_markets: List[Dict],
        polymarket_markets: List[Dict],
    ) -> List[CrossPlatformSignal]:
        """
        Find cross-platform arbitrage signals.

        Args:
            kalshi_markets: Normalized Kalshi market data
            polymarket_markets: Normalized Polymarket market data

        Returns:
            List of CrossPlatformSignal objects
        """
        signals = []

        if not self._polymarket_client:
            return signals

        # Find matches
        matches = self._polymarket_client.find_kalshi_matches(
            polymarket_markets=polymarket_markets,
            kalshi_markets=kalshi_markets,
        )

        logger.debug(f"Found {len(matches)} market matches")

        for match in matches:
            if not match.kalshi_market or not match.match_score:
                continue

            # Apply filters
            if match.match_score.total_score < self.min_match_score:
                continue

            poly_volume = match.polymarket_market.get("volume_24h", 0) or match.polymarket_market.get("volume", 0)
            if poly_volume < self.min_polymarket_volume:
                continue

            kalshi_volume = match.kalshi_market.get("volume", 0) or match.kalshi_market.get("volume_24h", 0)
            if kalshi_volume < self.min_kalshi_volume:
                continue

            # Get prices
            poly_price = match.polymarket_market.get("yes_bid", 0) or match.polymarket_market.get("last_price", 0)
            kalshi_price = match.kalshi_market.get("yes_bid", 0) or match.kalshi_market.get("last_price", 0)

            if not poly_price or not kalshi_price:
                continue

            # Calculate price difference
            price_diff = kalshi_price - poly_price

            # Check threshold
            if abs(price_diff) < self.price_diff_threshold:
                continue

            # Calculate volume momentum
            volume_momentum = self._calculate_volume_momentum(
                match.polymarket_market.get("ticker", ""),
                poly_volume,
            )

            # Apply volume confirmation if enabled
            if self.use_volume_confirmation and volume_momentum < self.volume_momentum_threshold:
                # Lower confidence if no volume momentum
                confidence_penalty = 0.2
            else:
                confidence_penalty = 0.0

            # Determine signal type
            if price_diff < 0:
                # Kalshi underpriced vs Polymarket -> BUY Kalshi
                signal_type = "buy"
                reasoning = (
                    f"Kalshi underpriced by {abs(price_diff)}c vs Polymarket. "
                    f"Poly={poly_price}c, Kalshi={kalshi_price}c. "
                    f"Match confidence: {match.match_score.total_score:.0%}"
                )
            else:
                # Kalshi overpriced vs Polymarket -> SELL Kalshi (or buy NO)
                signal_type = "sell"
                reasoning = (
                    f"Kalshi overpriced by {price_diff}c vs Polymarket. "
                    f"Poly={poly_price}c, Kalshi={kalshi_price}c. "
                    f"Match confidence: {match.match_score.total_score:.0%}"
                )

            # Calculate confidence
            # Higher price diff = higher confidence
            # Higher match score = higher confidence
            # Higher volume = higher confidence
            price_confidence = min(abs(price_diff) / 20, 1.0)  # Cap at 20c diff
            match_confidence = match.match_score.total_score
            volume_confidence = min(poly_volume / 100000, 1.0)  # Cap at 100k volume

            total_confidence = (
                0.4 * price_confidence +
                0.4 * match_confidence +
                0.2 * volume_confidence -
                confidence_penalty
            )
            total_confidence = max(0.1, min(1.0, total_confidence))

            signal = CrossPlatformSignal(
                polymarket_ticker=match.polymarket_market.get("ticker", ""),
                kalshi_ticker=match.kalshi_market.get("ticker", ""),
                polymarket_title=match.polymarket_market.get("title", ""),
                kalshi_title=match.kalshi_market.get("title", ""),
                polymarket_price=poly_price,
                kalshi_price=kalshi_price,
                price_diff_cents=price_diff,
                match_score=match.match_score.total_score,
                signal_type=signal_type,
                confidence=total_confidence,
                reasoning=reasoning,
                polymarket_volume=poly_volume,
                kalshi_volume=kalshi_volume,
                volume_momentum=volume_momentum,
                metadata={
                    "matched_keywords": match.match_score.matched_keywords,
                    "title_similarity": match.match_score.title_similarity,
                },
            )

            signals.append(signal)

        # Sort by confidence
        signals.sort(key=lambda s: s.confidence, reverse=True)

        return signals

    def _calculate_volume_momentum(
        self,
        ticker: str,
        current_volume: int,
    ) -> float:
        """
        Calculate volume momentum for a market.

        Tracks volume over time and calculates ratio vs. previous readings.

        Args:
            ticker: Market ticker
            current_volume: Current 24h volume

        Returns:
            Momentum ratio (1.0 = stable, >1 = increasing)
        """
        now = datetime.now()

        # Initialize history if needed
        if ticker not in self._volume_history:
            self._volume_history[ticker] = []

        history = self._volume_history[ticker]

        # Add current reading
        history.append((now, current_volume))

        # Keep only last 24 hours of readings
        cutoff = now - timedelta(hours=24)
        history = [(t, v) for t, v in history if t > cutoff]
        self._volume_history[ticker] = history

        # Need at least 2 readings for momentum
        if len(history) < 2:
            return 1.0

        # Compare current to oldest reading
        oldest_volume = history[0][1]
        if oldest_volume <= 0:
            return 1.0

        momentum = current_volume / oldest_volume
        return momentum

    def _signal_to_opportunity(
        self,
        signal: CrossPlatformSignal,
    ) -> Optional[TradingOpportunity]:
        """
        Convert CrossPlatformSignal to TradingOpportunity.

        Args:
            signal: Cross-platform arbitrage signal

        Returns:
            TradingOpportunity for Kalshi execution, or None if invalid
        """
        # Determine side based on signal type
        if signal.signal_type == "buy":
            side = "yes"
            entry_price = signal.kalshi_price
            # Target profit: convergence to Polymarket price
            expected_profit = abs(signal.price_diff_cents)
        else:
            # For "sell" signal, we buy NO (equivalent to selling YES)
            side = "no"
            entry_price = 100 - signal.kalshi_price  # NO price
            expected_profit = abs(signal.price_diff_cents)

        # Validate entry price
        if not (1 <= entry_price <= 99):
            logger.debug(f"Invalid entry price {entry_price} for {signal.kalshi_ticker}")
            return None

        # Calculate score (0-100)
        score = signal.confidence * 100

        return TradingOpportunity(
            ticker=signal.kalshi_ticker,
            title=signal.kalshi_title,
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=signal.kalshi_price,
            current_no_price=100 - signal.kalshi_price,
            volume=signal.kalshi_volume,
            score=score,
            reasoning=signal.reasoning,
            expected_profit_cents=expected_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "signal_type": signal.signal_type,
                "polymarket_ticker": signal.polymarket_ticker,
                "polymarket_price": signal.polymarket_price,
                "price_diff_cents": signal.price_diff_cents,
                "match_score": signal.match_score,
                "polymarket_volume": signal.polymarket_volume,
                "volume_momentum": signal.volume_momentum,
                "matched_keywords": signal.metadata.get("matched_keywords", []),
            },
        )

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """
        Check if cross-platform position should be exited.

        Exit conditions:
        1. Take profit: Price converged toward Polymarket price
        2. Stop loss: Price moved against us
        3. Signal invalidated: Polymarket price changed significantly
        4. Time-based: Holding too long without convergence

        Args:
            position: Position data with entry_price, side, metadata
            current_price: Current Kalshi price for position side
            market_data: Optional market data

        Returns:
            ExitSignal with recommendation
        """
        entry_price = position.get("entry_price", 50)
        side = position.get("side", "yes")
        entry_time = position.get("entry_time")
        metadata = position.get("metadata", {})

        # Calculate P&L
        pnl_cents = current_price - entry_price

        # Get original signal info
        original_poly_price = metadata.get("polymarket_price", 0)
        original_price_diff = metadata.get("price_diff_cents", 0)

        # Check take profit
        if pnl_cents >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit reached: +{pnl_cents}c (target: +{self.take_profit}c)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        # Check stop loss
        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss triggered: {pnl_cents}c (limit: -{self.stop_loss}c)",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.9,
            )

        # Check price convergence (main thesis)
        # If Kalshi price has moved toward where Polymarket was, we've captured value
        if original_price_diff != 0:
            # Calculate how much of the gap we've captured
            current_diff = current_price - original_poly_price
            convergence = 1 - (abs(current_diff) / abs(original_price_diff))

            if convergence >= 0.8:  # 80% convergence
                return ExitSignal(
                    should_exit=True,
                    reason=f"Price convergence: {convergence:.0%} of gap captured. P&L: {pnl_cents:+d}c",
                    exit_type="take_profit",
                    current_price_cents=current_price,
                    pnl_cents=pnl_cents,
                    urgency=0.7,
                )

        # Check time-based exit (if position too old without convergence)
        if entry_time:
            try:
                if isinstance(entry_time, str):
                    entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                else:
                    entry_dt = entry_time

                holding_time = (datetime.now(entry_dt.tzinfo) - entry_dt).total_seconds() / 3600

                # Exit after 24 hours if not profitable
                if holding_time > 24 and pnl_cents <= 0:
                    return ExitSignal(
                        should_exit=True,
                        reason=f"Time-based exit: Held {holding_time:.1f}h without profit. P&L: {pnl_cents:+d}c",
                        exit_type="manual",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.5,
                    )
            except (ValueError, TypeError, AttributeError):
                pass

        # Default: hold
        return ExitSignal(
            should_exit=False,
            reason=f"Holding cross-platform position. Current P&L: {pnl_cents:+d}c",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """
        Get hardcoded prior statistics for Kelly calculation.

        Cross-platform arbitrage stats are based on:
        - Market matching accuracy
        - Price convergence frequency
        - Execution success rate

        Returns:
            Dict with win_rate, avg_win_cents, avg_loss_cents
        """
        # Neutral priors — let Bayesian learning converge to reality
        return {
            "win_rate": 0.50,
            "avg_win_cents": 6.0,
            "avg_loss_cents": 6.0,
        }

    def validate_config(self) -> tuple[bool, str]:
        """Validate strategy-specific configuration."""
        valid, error = super().validate_config()
        if not valid:
            return valid, error

        if self.price_diff_threshold < 1:
            return False, "price_diff_threshold_cents must be at least 1"

        if not (0 < self.min_match_score <= 1):
            return False, "min_match_score must be between 0 and 1"

        if self.min_polymarket_volume < 0:
            return False, "min_polymarket_volume cannot be negative"

        if self.volume_momentum_threshold < 1:
            return False, "volume_momentum_threshold must be >= 1"

        return True, ""

    async def refresh_polymarket_data(self) -> None:
        """
        Refresh Polymarket market data cache.

        Called periodically by the orchestrator to keep data fresh.
        """
        if self._polymarket_client:
            await self._polymarket_client.get_open_markets(limit=200)
            logger.debug(f"[{self.name}] Refreshed Polymarket data cache")

    def get_active_signals(self) -> Dict[str, CrossPlatformSignal]:
        """
        Get all active cross-platform signals.

        Returns:
            Dict mapping Kalshi ticker to CrossPlatformSignal
        """
        return self._active_signals.copy()

    def clear_signal(self, kalshi_ticker: str) -> None:
        """
        Clear a signal after position exit.

        Args:
            kalshi_ticker: Kalshi market ticker
        """
        if kalshi_ticker in self._active_signals:
            del self._active_signals[kalshi_ticker]
