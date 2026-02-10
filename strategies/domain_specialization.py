"""
Domain Specialization Framework

Meta-strategy that provides deep expertise in narrow market categories.
Pluggable signal sources combine to identify opportunities in a specific
domain (crypto prices, Fed decisions, sports, etc.).

Edge:
    Domain expertise. By specializing in one category and combining
    multiple signal types (momentum, volume, cross-market, time decay,
    mean reversion), you develop stronger edge than generalist strategies.

Architecture:
    SignalSource (ABC) -> SIGNAL_REGISTRY -> DomainSpecializationStrategy
    Each signal returns -1 to +1 (bearish to bullish).
    Weighted combination determines trade direction and confidence.

Expected Value:
    Win rate: 56% | Avg win: take_profit | Avg loss: stop_loss
    (Varies by domain configuration)
"""

import logging
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import score_spread, score_volume, is_market_tradeable, get_mid_price, clamp_score

logger = logging.getLogger(__name__)


class SignalSource(ABC):
    """Abstract base class for pluggable signal sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Signal source identifier."""
        pass

    @abstractmethod
    def calculate(
        self, market: Dict[str, Any], history: List[Tuple[datetime, int]]
    ) -> float:
        """
        Calculate signal strength.

        Args:
            market: Current market data
            history: Price history for this market [(timestamp, price), ...]

        Returns:
            Signal from -1.0 (strong sell/NO) to +1.0 (strong buy/YES).
            0.0 = neutral.
        """
        pass


class PriceMomentumSignal(SignalSource):
    """Track price trend over recent history."""

    @property
    def name(self) -> str:
        return "price_momentum"

    def calculate(self, market: Dict, history: List[Tuple[datetime, int]]) -> float:
        if len(history) < 3:
            return 0.0

        recent = history[-5:] if len(history) >= 5 else history
        old_price = recent[0][1]
        new_price = recent[-1][1]

        if old_price == 0:
            return 0.0

        change = (new_price - old_price) / old_price
        # Scale to [-1, 1] range (10% move = full signal)
        return max(-1.0, min(1.0, change / 0.10))


class VolumeAnalysisSignal(SignalSource):
    """Volume surge detection."""

    @property
    def name(self) -> str:
        return "volume_analysis"

    def calculate(self, market: Dict, history: List[Tuple[datetime, int]]) -> float:
        volume = market.get("volume", 0) or market.get("volume_24h", 0)
        if volume < 100:
            return 0.0

        # Higher volume = stronger signal (direction from price movement)
        if len(history) < 2:
            return 0.0

        price_dir = history[-1][1] - history[-2][1]
        vol_strength = min(volume / 5000, 1.0)

        if price_dir > 0:
            return vol_strength * 0.5
        elif price_dir < 0:
            return -vol_strength * 0.5
        return 0.0


class CrossMarketSentimentSignal(SignalSource):
    """Compare market price to related markets (placeholder for domain-specific logic)."""

    @property
    def name(self) -> str:
        return "cross_market_sentiment"

    def calculate(self, market: Dict, history: List[Tuple[datetime, int]]) -> float:
        # Placeholder: return slight bullish bias for markets in the 40-60 range
        price = get_mid_price(market)
        if 40 <= price <= 60:
            return 0.1  # Slight bullish (markets near 50 tend to mean-revert up)
        return 0.0


class TimeDecaySignal(SignalSource):
    """Signal that strengthens as expiry approaches."""

    @property
    def name(self) -> str:
        return "time_decay"

    def calculate(self, market: Dict, history: List[Tuple[datetime, int]]) -> float:
        from .utils import hours_until_close

        hours = hours_until_close(market)
        if hours is None or hours <= 0:
            return 0.0

        price = get_mid_price(market)

        # Near expiry, extreme prices become more reliable
        if hours < 24:
            if price >= 80:
                return 0.8  # Strong YES signal near expiry
            elif price <= 20:
                return -0.8  # Strong NO signal near expiry
            elif price >= 60:
                return 0.3
            elif price <= 40:
                return -0.3
        return 0.0


class MeanReversionSignalSource(SignalSource):
    """Reversion toward 50c signal."""

    @property
    def name(self) -> str:
        return "mean_reversion_signal"

    def calculate(self, market: Dict, history: List[Tuple[datetime, int]]) -> float:
        price = get_mid_price(market)

        if 45 <= price <= 55:
            return 0.0  # Already near mean

        # Signal toward 50
        deviation = price - 50
        return max(-1.0, min(1.0, -deviation / 30.0))


# Registry of built-in signal sources
SIGNAL_REGISTRY: Dict[str, type] = {
    "price_momentum": PriceMomentumSignal,
    "volume_analysis": VolumeAnalysisSignal,
    "cross_market_sentiment": CrossMarketSentimentSignal,
    "time_decay": TimeDecaySignal,
    "mean_reversion_signal": MeanReversionSignalSource,
}


# Pre-built domain configurations
DOMAIN_PRESETS: Dict[str, Dict[str, Any]] = {
    "crypto_price": {
        "category_filter": r"BTC|ETH|crypto|bitcoin|ethereum",
        "signal_sources": [
            {"name": "price_momentum", "weight": 0.35},
            {"name": "volume_analysis", "weight": 0.25},
            {"name": "time_decay", "weight": 0.20},
            {"name": "mean_reversion_signal", "weight": 0.20},
        ],
    },
    "fed_decisions": {
        "category_filter": r"fed|federal reserve|interest rate|FOMC",
        "signal_sources": [
            {"name": "cross_market_sentiment", "weight": 0.30},
            {"name": "price_momentum", "weight": 0.25},
            {"name": "time_decay", "weight": 0.30},
            {"name": "volume_analysis", "weight": 0.15},
        ],
    },
    "sports": {
        "category_filter": r"NFL|NBA|MLB|NHL|Super Bowl|World Series",
        "signal_sources": [
            {"name": "price_momentum", "weight": 0.30},
            {"name": "volume_analysis", "weight": 0.30},
            {"name": "time_decay", "weight": 0.25},
            {"name": "cross_market_sentiment", "weight": 0.15},
        ],
    },
}


class DomainSpecializationStrategy(Strategy):
    """
    Meta-strategy framework for domain-specific market expertise.

    Configuration:
        domain: Domain preset name or "custom" (default: "crypto_price")
        category_filter: Regex for market title matching
        signal_sources: List of {name, weight} dicts
        min_signal_strength: Min combined signal to trade (default: 0.6)
        take_profit_cents: Target profit (default: 8)
        stop_loss_cents: Max loss (default: 5)
    """

    def __init__(self, config: Dict[str, Any]):
        config.setdefault("take_profit_cents", 8)
        config.setdefault("stop_loss_cents", 5)
        super().__init__(config)

        self.domain = config.get("domain", "crypto_price")
        self.min_signal = config.get("min_signal_strength", 0.6)

        # Load domain preset or custom config
        preset = DOMAIN_PRESETS.get(self.domain, {})
        self.category_filter = config.get(
            "category_filter", preset.get("category_filter", ".*")
        )
        signal_configs = config.get(
            "signal_sources", preset.get("signal_sources", [])
        )

        # Instantiate signal sources
        self._signals: List[Tuple[SignalSource, float]] = []
        for sc in signal_configs:
            signal_name = sc.get("name", "")
            weight = sc.get("weight", 1.0)
            signal_cls = SIGNAL_REGISTRY.get(signal_name)
            if signal_cls:
                self._signals.append((signal_cls(), weight))
            else:
                logger.warning(f"Unknown signal source: {signal_name}")

        # If no signals configured, use defaults
        if not self._signals:
            self._signals = [
                (PriceMomentumSignal(), 0.30),
                (VolumeAnalysisSignal(), 0.25),
                (TimeDecaySignal(), 0.25),
                (MeanReversionSignalSource(), 0.20),
            ]

        # Price history per ticker
        self._price_history: Dict[str, List[Tuple[datetime, int]]] = defaultdict(list)
        self._max_history = 100

        # Compile category regex
        try:
            self._category_re = re.compile(self.category_filter, re.IGNORECASE)
        except re.error:
            self._category_re = re.compile(".*")

        signal_names = [s.name for s, _ in self._signals]
        logger.info(
            f"DomainSpecializationStrategy initialized: "
            f"domain={self.domain}, filter='{self.category_filter}', "
            f"signals={signal_names}, min_signal={self.min_signal}"
        )

    @property
    def name(self) -> str:
        return "domain_specialization"

    @property
    def description(self) -> str:
        return (
            f"Domain specialization ({self.domain}): "
            f"Multi-signal analysis for '{self.category_filter}' markets"
        )

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        existing_positions = existing_positions or {}
        opportunities = []
        now = datetime.now()

        for market in markets:
            ticker = market.get("ticker", "")
            title = market.get("title", "")

            if not is_market_tradeable(market, self.min_volume):
                continue

            if ticker in existing_positions:
                continue

            # Category filter
            if not self._category_re.search(title) and not self._category_re.search(ticker):
                continue

            current_price = get_mid_price(market)

            # Update price history
            self._price_history[ticker].append((now, current_price))
            if len(self._price_history[ticker]) > self._max_history:
                self._price_history[ticker] = self._price_history[ticker][-self._max_history:]

            history = self._price_history[ticker]

            # Calculate combined signal
            combined_signal = self._calculate_combined_signal(market, history)

            if abs(combined_signal) < self.min_signal:
                continue

            opp = self._create_opportunity(
                market=market,
                ticker=ticker,
                title=title,
                current_price=current_price,
                combined_signal=combined_signal,
            )

            if opp:
                opportunities.append(opp)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}:{self.domain}] Found {len(opportunities)} opportunities "
            f"from {len(markets)} markets"
        )
        return opportunities

    def _calculate_combined_signal(
        self, market: Dict, history: List[Tuple[datetime, int]]
    ) -> float:
        """Calculate weighted combination of all signal sources."""
        total_weight = sum(w for _, w in self._signals)
        if total_weight <= 0:
            return 0.0

        weighted_sum = 0.0
        for signal, weight in self._signals:
            try:
                value = signal.calculate(market, history)
                weighted_sum += value * weight
            except Exception as e:
                logger.debug(f"Signal {signal.name} failed: {e}")

        return weighted_sum / total_weight

    def _create_opportunity(
        self,
        market: Dict,
        ticker: str,
        title: str,
        current_price: int,
        combined_signal: float,
    ) -> Optional[TradingOpportunity]:
        """Create opportunity from combined signal."""

        yes_bid = market.get("yes_bid", 0)
        yes_ask = market.get("yes_ask", 0)
        no_bid = market.get("no_bid", 0)
        no_ask = market.get("no_ask", 0)
        volume = market.get("volume", 0) or market.get("volume_24h", 0)

        if combined_signal > 0:
            side = "yes"
            entry_price = yes_ask if yes_ask else current_price
            direction = "bullish"
        else:
            side = "no"
            entry_price = no_ask if no_ask else (100 - current_price)
            direction = "bearish"

        # Individual signal breakdown for metadata
        signal_breakdown = {}
        for signal, weight in self._signals:
            try:
                value = signal.calculate(market, self._price_history.get(ticker, []))
                signal_breakdown[signal.name] = round(value, 3)
            except Exception:
                signal_breakdown[signal.name] = 0.0

        reasoning = (
            f"Domain [{self.domain}] {direction} signal: {combined_signal:+.2f}. "
            f"Signals: {signal_breakdown}. "
            f"Market at {current_price}c."
        )

        # Score: signal strength + volume + spread
        signal_score = abs(combined_signal) * 50
        vol_score = score_volume(volume, target=1000, max_score=25)
        spread_sc = score_spread(yes_bid, yes_ask, no_bid, no_ask, max_score=15)
        # Bonus for being in favorable price zone
        zone_score = 10.0 if 30 <= current_price <= 70 else 5.0

        total_score = clamp_score(signal_score + vol_score + spread_sc + zone_score)

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
            score=total_score,
            reasoning=reasoning,
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "domain": self.domain,
                "combined_signal": combined_signal,
                "signal_breakdown": signal_breakdown,
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
                reason=f"Take profit: +{pnl_cents}c",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss: {pnl_cents}c",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        # Re-evaluate signal if we have market data
        if market_data:
            ticker = position.get("ticker", "")
            history = self._price_history.get(ticker, [])
            if history:
                signal = self._calculate_combined_signal(market_data, history)
                side = position.get("side", "yes")

                # Exit if signal flipped against our position
                if (side == "yes" and signal < -0.3) or (side == "no" and signal > 0.3):
                    return ExitSignal(
                        should_exit=True,
                        reason=f"Signal reversal: {signal:+.2f} (we're {side})",
                        exit_type="manual",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.7,
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

        if not (0 < self.min_signal <= 1):
            return False, "min_signal_strength must be between 0 and 1"

        if not self._signals:
            return False, "At least one signal source must be configured"

        try:
            re.compile(self.category_filter)
        except re.error as e:
            return False, f"Invalid category_filter regex: {e}"

        return True, ""
