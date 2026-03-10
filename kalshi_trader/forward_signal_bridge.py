"""
Forward Signal Bridge — Cross-Market Intelligence Layer

Monitors Kalshi prediction market price movements as LEADING indicators
for stock/futures/options strategies. Prediction markets are crowd-sourced
forward-looking bets — when they move, it's because the collective
intelligence is repricing the future BEFORE traditional markets react.

Signal taxonomy:
    RATE_SHIFT    — KXFED prices moving = rate expectations changing
                    Bearish for stocks if pricing higher rates
                    Bullish for bonds if pricing lower rates

    INFLATION     — KXCPI prices moving = inflation expectations changing
                    Bullish for gold/oil if inflation rising
                    Bearish for growth stocks if inflation rising

    GROWTH        — KXGDP prices moving = growth expectations changing
                    Bearish for everything if growth collapsing
                    Bullish for cyclicals if growth accelerating

    RISK_APPETITE — KXBTC/KXETH prices moving = crypto risk appetite
                    Crypto leads risk-on/risk-off sentiment by hours
                    Rising crypto = risk-on, falling = risk-off

Architecture:
    ForwardSignalBridge sits between the Kalshi market scanner and the
    GovernanceEngine. Each trading cycle:
    1. Records latest Kalshi prices by series
    2. Computes price velocity (change per cycle) for each series
    3. Detects significant shifts (>threshold over rolling window)
    4. Translates shifts into ForwardSignals with direction + confidence
    5. GovernanceEngine consumes signals to bias regime detection
    6. Strategies see regime shifts FASTER than stock-price-only detection

The bridge is the "sight" layer — it sees around corners by reading
what the crowd is betting on before the market prices it in.
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Categories of forward-looking signals from prediction markets."""
    RATE_SHIFT = "rate_shift"          # Fed funds rate expectations
    INFLATION = "inflation"            # CPI / inflation expectations
    GROWTH = "growth"                  # GDP / economic growth
    RISK_APPETITE = "risk_appetite"    # Crypto as risk-on/risk-off proxy
    GEOPOLITICAL = "geopolitical"      # War, sanctions, political events


class SignalDirection(Enum):
    """Direction of a forward signal."""
    BULLISH = "bullish"      # Favorable for stocks / risk assets
    BEARISH = "bearish"      # Unfavorable for stocks / risk assets
    NEUTRAL = "neutral"      # No clear direction


@dataclass
class ForwardSignal:
    """A forward-looking signal derived from prediction market movements."""
    signal_type: SignalType
    direction: SignalDirection
    confidence: float          # 0.0-1.0 — how strong is this signal
    magnitude: float           # Raw magnitude of the shift (in cents)
    source_series: str         # Which Kalshi series generated this
    description: str           # Human-readable explanation
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_significant(self) -> bool:
        return self.confidence >= 0.3 and self.direction != SignalDirection.NEUTRAL


@dataclass
class MarketPricePoint:
    """A price observation for a prediction market series."""
    series: str
    timestamp: datetime
    avg_price: float           # Volume-weighted average price across contracts
    total_volume: int          # Aggregate volume
    contract_count: int        # Number of active contracts
    price_spread: float        # Max price - min price (market uncertainty)


# Series -> Signal type mapping
SERIES_SIGNAL_MAP = {
    "KXFED": SignalType.RATE_SHIFT,
    "KXCPI": SignalType.INFLATION,
    "KXGDP": SignalType.GROWTH,
    "KXBTC": SignalType.RISK_APPETITE,
    "KXETH": SignalType.RISK_APPETITE,
}

# How each signal type affects stock market direction
# Positive magnitude = bullish for stocks, negative = bearish
SIGNAL_STOCK_IMPACT = {
    SignalType.RATE_SHIFT: {
        # Higher rates = bearish for stocks (tighter money)
        # KXFED prices rising for higher rate brackets = bearish
        "invert": True,  # Higher probability of rate hike = bearish
        "threshold_cents": 3.0,
        "weight": 0.25,
    },
    SignalType.INFLATION: {
        # Higher inflation = mixed, but generally bearish for growth
        # KXCPI prices rising for higher brackets = bearish
        "invert": True,
        "threshold_cents": 3.0,
        "weight": 0.20,
    },
    SignalType.GROWTH: {
        # Higher GDP = bullish for stocks
        # KXGDP prices rising for higher brackets = bullish
        "invert": False,
        "threshold_cents": 4.0,
        "weight": 0.25,
    },
    SignalType.RISK_APPETITE: {
        # Crypto rising = risk-on = bullish for stocks
        # Crypto falling = risk-off = bearish
        "invert": False,
        "threshold_cents": 2.0,
        "weight": 0.30,
    },
    SignalType.GEOPOLITICAL: {
        # Geopolitical risk = bearish for equities, bullish for oil/gold/defense
        # News-driven — no price inversion, signal arrives pre-scored
        "invert": False,
        "threshold_cents": 0.0,  # N/A for news signals (uses confidence directly)
        "weight": 0.20,
    },
}


class ForwardSignalBridge:
    """
    Monitors prediction market movements and generates forward-looking signals.

    Sits between the Kalshi scanner and the GovernanceEngine, translating
    prediction market price velocity into regime-influencing signals.
    """

    TESTING_MODE: bool = False

    def __init__(
        self,
        lookback_cycles: int = 10,
        signal_decay_cycles: int = 5,
    ):
        self.lookback_cycles = lookback_cycles
        self.signal_decay_cycles = signal_decay_cycles
        self._testing_mode: bool = self.__class__.TESTING_MODE

        # Rolling price history per series: deque of MarketPricePoint
        self._price_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=lookback_cycles)
        )

        # Active forward signals (decayed over time)
        self._active_signals: List[ForwardSignal] = []
        self._signal_cycle_age: Dict[str, int] = {}  # signal_id -> cycles since emission

        # Composite forward view
        self._composite_direction: SignalDirection = SignalDirection.NEUTRAL
        self._composite_confidence: float = 0.0

        logger.info(
            "ForwardSignalBridge initialized | lookback=%d cycles, decay=%d cycles, testing_mode=%s",
            lookback_cycles, signal_decay_cycles, self._testing_mode,
        )

    def set_testing_mode(self, enabled: bool) -> None:
        """Enable/disable testing mode. When on, detection thresholds are halved."""
        self._testing_mode = enabled
        logger.info("ForwardSignalBridge testing_mode=%s (thresholds %s)",
                     enabled, "halved" if enabled else "normal")

    def ingest_kalshi_markets(self, markets: List[Dict], series: str) -> None:
        """Ingest a batch of Kalshi markets from a single series scan.

        Called each trading cycle with the markets returned by the Kalshi
        scanner for a specific series (e.g., KXFED, KXBTC).
        """
        if not markets:
            return

        if series not in SERIES_SIGNAL_MAP:
            return

        # Compute volume-weighted average price and spread
        prices = []
        total_vol = 0
        weighted_sum = 0.0

        for m in markets:
            status = m.get("status", "")
            if status not in ("open", "active"):
                continue

            yes_price = m.get("yes_bid", 0) or m.get("yes_ask", 0)
            vol = m.get("volume", 0)
            if yes_price > 0:
                prices.append(yes_price)
                weighted_sum += yes_price * max(vol, 1)
                total_vol += max(vol, 1)

        if not prices or total_vol == 0:
            return

        avg_price = weighted_sum / total_vol
        price_spread = max(prices) - min(prices)

        point = MarketPricePoint(
            series=series,
            timestamp=datetime.now(timezone.utc),
            avg_price=avg_price,
            total_volume=total_vol,
            contract_count=len(prices),
            price_spread=price_spread,
        )

        self._price_history[series].append(point)

    def ingest_news_signal(self, signal: dict) -> Optional[ForwardSignal]:
        """Convert a news feed signal dict into a ForwardSignal and add it to active signals.

        Accepts the output of NewsFeed.get_latest_signal().to_dict() or
        NewsFeed.get_geopolitical_signal().to_dict().

        The news signal bypasses price-history detection — it arrives pre-scored
        from the NewsFeed keyword engine and is injected directly into the
        active signal pool where it ages out via the normal decay mechanism.
        """
        direction_str = signal.get("direction", "neutral")
        confidence = signal.get("confidence", 0.0)

        if direction_str == "bullish":
            direction = SignalDirection.BULLISH
        elif direction_str == "bearish":
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL

        # Determine signal type: geopolitical if flagged, otherwise general news sentiment
        is_geo = signal.get("geopolitical", False)
        signal_type = SignalType.GEOPOLITICAL if is_geo else SignalType.RISK_APPETITE

        keywords = signal.get("keywords_matched", [])
        headline_count = signal.get("headline_count", 0)
        source = signal.get("source", "rss")

        # Build description
        kw_sample = ", ".join(keywords[:5])
        if is_geo:
            desc = (
                f"Geopolitical risk detected: {len(keywords)} keywords "
                f"across {headline_count} headlines ({kw_sample})"
            )
        else:
            desc = (
                f"News sentiment {direction_str}: {len(keywords)} keywords "
                f"across {headline_count} headlines ({kw_sample})"
            )

        impact = SIGNAL_STOCK_IMPACT.get(signal_type, {})
        weight = impact.get("weight", 0.20)

        forward_signal = ForwardSignal(
            signal_type=signal_type,
            direction=direction,
            confidence=round(confidence, 3),
            magnitude=0.0,  # No price magnitude for news signals
            source_series=f"NEWS_{source.upper()}",
            description=desc,
            metadata={
                "keywords_matched": keywords,
                "headline_count": headline_count,
                "source": source,
                "weight": weight,
                "news_driven": True,
            },
        )

        if not forward_signal.is_significant:
            return None

        # Inject directly into active signals (skip price-history detection path)
        self._active_signals.append(forward_signal)
        self._signal_cycle_age[id(forward_signal)] = 0
        self._update_composite()

        logger.info(
            "News signal ingested: %s %s (conf=%.2f, %d keywords, %d headlines) — %s",
            signal_type.value, direction.value, confidence,
            len(keywords), headline_count, desc,
        )

        return forward_signal

    def detect_signals(self) -> List[ForwardSignal]:
        """Analyze price history and emit forward signals.

        Called once per trading cycle after all series have been ingested.
        Returns new signals detected this cycle.
        """
        new_signals = []

        for series, history in self._price_history.items():
            if len(history) < 3:
                continue  # Need at least 3 data points for velocity

            signal_type = SERIES_SIGNAL_MAP.get(series)
            if not signal_type:
                continue

            impact = SIGNAL_STOCK_IMPACT.get(signal_type)
            if not impact:
                continue

            # Compute price velocity: change from oldest to newest in window
            oldest = history[0]
            newest = history[-1]
            price_delta = newest.avg_price - oldest.avg_price

            # Also check short-term acceleration (last 3 cycles)
            if len(history) >= 3:
                recent_delta = history[-1].avg_price - history[-3].avg_price
            else:
                recent_delta = price_delta

            threshold = impact["threshold_cents"]
            if self._testing_mode:
                threshold *= 0.5

            # Check if shift is significant
            if abs(price_delta) < threshold and abs(recent_delta) < threshold * 0.7:
                continue

            # Determine direction
            # price_delta > 0 means prices are rising for this series
            raw_direction = price_delta if not impact["invert"] else -price_delta

            if raw_direction > 0:
                direction = SignalDirection.BULLISH
            elif raw_direction < 0:
                direction = SignalDirection.BEARISH
            else:
                direction = SignalDirection.NEUTRAL

            # Confidence based on magnitude relative to threshold + data quality
            magnitude = max(abs(price_delta), abs(recent_delta))
            confidence = min(1.0, magnitude / (threshold * 3))

            # Boost confidence if acceleration confirms direction
            if (price_delta > 0 and recent_delta > 0) or (price_delta < 0 and recent_delta < 0):
                confidence = min(1.0, confidence * 1.3)

            # Volume confirmation: higher volume = more reliable signal
            avg_vol = sum(p.total_volume for p in history) / len(history)
            if avg_vol > 1000:
                confidence = min(1.0, confidence * 1.1)

            # Spread confirmation: narrowing spread = more consensus
            spread_trend = newest.price_spread - oldest.price_spread
            if spread_trend < 0:  # Spread narrowing = stronger conviction
                confidence = min(1.0, confidence * 1.1)

            signal = ForwardSignal(
                signal_type=signal_type,
                direction=direction,
                confidence=round(confidence, 3),
                magnitude=round(price_delta, 2),
                source_series=series,
                description=self._describe_signal(signal_type, direction, price_delta, series),
                metadata={
                    "price_delta": round(price_delta, 2),
                    "recent_delta": round(recent_delta, 2),
                    "avg_volume": int(avg_vol),
                    "spread_trend": round(spread_trend, 2),
                    "lookback_cycles": len(history),
                    "weight": impact["weight"],
                },
            )

            if signal.is_significant:
                new_signals.append(signal)
                logger.info(
                    "Forward signal: %s %s (conf=%.2f, delta=%.1fc) from %s — %s",
                    signal_type.value, direction.value, confidence,
                    price_delta, series, signal.description,
                )

        # Update active signals: add new, age existing, prune expired
        self._active_signals = [
            s for s in self._active_signals
            if self._signal_cycle_age.get(id(s), 0) < self.signal_decay_cycles
        ]
        for s in new_signals:
            self._active_signals.append(s)
            self._signal_cycle_age[id(s)] = 0

        # Age all signals
        for s in self._active_signals:
            self._signal_cycle_age[id(s)] = self._signal_cycle_age.get(id(s), 0) + 1

        # Recompute composite view
        self._update_composite()

        return new_signals

    def _update_composite(self) -> None:
        """Recompute composite forward direction from all active signals."""
        if not self._active_signals:
            self._composite_direction = SignalDirection.NEUTRAL
            self._composite_confidence = 0.0
            return

        bullish_weight = 0.0
        bearish_weight = 0.0

        for signal in self._active_signals:
            age = self._signal_cycle_age.get(id(signal), 0)
            decay = max(0.1, 1.0 - (age / self.signal_decay_cycles))
            weight = signal.metadata.get("weight", 0.2) * signal.confidence * decay

            if signal.direction == SignalDirection.BULLISH:
                bullish_weight += weight
            elif signal.direction == SignalDirection.BEARISH:
                bearish_weight += weight

        total = bullish_weight + bearish_weight
        if total == 0:
            self._composite_direction = SignalDirection.NEUTRAL
            self._composite_confidence = 0.0
            return

        if bullish_weight > bearish_weight:
            self._composite_direction = SignalDirection.BULLISH
            self._composite_confidence = round((bullish_weight - bearish_weight) / total, 3)
        elif bearish_weight > bullish_weight:
            self._composite_direction = SignalDirection.BEARISH
            self._composite_confidence = round((bearish_weight - bullish_weight) / total, 3)
        else:
            self._composite_direction = SignalDirection.NEUTRAL
            self._composite_confidence = 0.0

    def get_composite_signal(self) -> Dict[str, Any]:
        """Get the composite forward view for the governance engine.

        Returns a dict that can be injected into the CycleAnalyzer's
        external signal path, biasing regime prediction.
        """
        return {
            "direction": self._composite_direction.value,
            "confidence": self._composite_confidence,
            "active_signals": len(self._active_signals),
            "signal_breakdown": {
                s.signal_type.value: {
                    "direction": s.direction.value,
                    "confidence": s.confidence,
                    "magnitude": s.magnitude,
                    "source": s.source_series,
                }
                for s in self._active_signals
            },
        }

    def get_regime_bias(self) -> Optional[Dict[str, float]]:
        """Translate composite signal into a regime bias for the CycleAnalyzer.

        Returns a dict of {regime_name: weight} that biases the next
        regime prediction, or None if no significant signal.
        """
        if self._composite_confidence < 0.2:
            return None

        from .market_governor import MarketRegime

        bias: Dict[MarketRegime, float] = {}

        if self._composite_direction == SignalDirection.BEARISH:
            bias[MarketRegime.TRENDING_DOWN] = self._composite_confidence * 0.6
            bias[MarketRegime.HIGH_VOL_CHOPPY] = self._composite_confidence * 0.3
        elif self._composite_direction == SignalDirection.BULLISH:
            bias[MarketRegime.TRENDING_UP] = self._composite_confidence * 0.6
            bias[MarketRegime.LOW_VOL_CALM] = self._composite_confidence * 0.2

        if not bias:
            return None

        return {r.value: w for r, w in bias.items()}

    def get_strategy_adjustments(self) -> Dict[str, Dict[str, Any]]:
        """Generate per-strategy adjustments based on forward signals.

        Returns dict of strategy_name -> adjustment hints that strategies
        can use to modify their behavior before the stock regime catches up.
        """
        adjustments: Dict[str, Dict[str, Any]] = {}

        for signal in self._active_signals:
            if not signal.is_significant:
                continue

            # Rate shift signals
            if signal.signal_type == SignalType.RATE_SHIFT:
                if signal.direction == SignalDirection.BEARISH:
                    adjustments["stock_momentum"] = {
                        "score_penalty": 15,
                        "reason": f"Forward: rate hike signal from {signal.source_series}",
                    }
                    adjustments["crisis_alpha"] = {
                        "score_bonus": 10,
                        "activate_types": ["safe_haven", "inverse_equity"],
                        "reason": f"Forward: rate hike = risk-off from {signal.source_series}",
                    }

            # Inflation signals
            elif signal.signal_type == SignalType.INFLATION:
                if signal.direction == SignalDirection.BEARISH:
                    adjustments["crisis_alpha"] = adjustments.get("crisis_alpha", {})
                    adjustments["crisis_alpha"].update({
                        "score_bonus": adjustments.get("crisis_alpha", {}).get("score_bonus", 0) + 10,
                        "activate_types": ["energy", "safe_haven"],
                        "reason": f"Forward: inflation rising from {signal.source_series}",
                    })

            # Growth signals
            elif signal.signal_type == SignalType.GROWTH:
                if signal.direction == SignalDirection.BEARISH:
                    adjustments["futures_trend"] = {
                        "direction_bias": "sell",
                        "confidence_boost": 0.1,
                        "reason": f"Forward: growth slowing from {signal.source_series}",
                    }
                    adjustments["crisis_alpha"] = adjustments.get("crisis_alpha", {})
                    adjustments["crisis_alpha"].update({
                        "score_bonus": adjustments.get("crisis_alpha", {}).get("score_bonus", 0) + 15,
                        "reason": f"Forward: recession signal from {signal.source_series}",
                    })

            # Risk appetite signals (crypto leading)
            elif signal.signal_type == SignalType.RISK_APPETITE:
                if signal.direction == SignalDirection.BEARISH:
                    adjustments["stock_momentum"] = adjustments.get("stock_momentum", {})
                    adjustments["stock_momentum"].update({
                        "score_penalty": adjustments.get("stock_momentum", {}).get("score_penalty", 0) + 10,
                        "reason": f"Forward: risk-off from crypto ({signal.source_series})",
                    })
                elif signal.direction == SignalDirection.BULLISH:
                    adjustments["stock_momentum"] = adjustments.get("stock_momentum", {})
                    adjustments["stock_momentum"].update({
                        "score_bonus": 5,
                        "reason": f"Forward: risk-on from crypto ({signal.source_series})",
                    })

        return adjustments

    def get_status_summary(self) -> str:
        """Human-readable summary for Captain's Log / Telegram."""
        if not self._active_signals:
            return "Forward signals: quiet — no significant prediction market shifts"

        lines = [
            f"Forward view: {self._composite_direction.value} "
            f"(conf={self._composite_confidence:.0%}, "
            f"{len(self._active_signals)} active signals)"
        ]
        for s in self._active_signals:
            age = self._signal_cycle_age.get(id(s), 0)
            lines.append(
                f"  {s.signal_type.value}: {s.direction.value} "
                f"({s.magnitude:+.1f}c from {s.source_series}, "
                f"age={age}/{self.signal_decay_cycles})"
            )
        return "\n".join(lines)

    @staticmethod
    def _describe_signal(
        signal_type: SignalType,
        direction: SignalDirection,
        delta: float,
        series: str,
    ) -> str:
        """Generate a human-readable description of a forward signal."""
        descriptions = {
            (SignalType.RATE_SHIFT, SignalDirection.BEARISH):
                f"{series} pricing higher rates ({delta:+.1f}c) — tighter money ahead, bearish for stocks",
            (SignalType.RATE_SHIFT, SignalDirection.BULLISH):
                f"{series} pricing lower rates ({delta:+.1f}c) — easier money ahead, bullish for stocks",
            (SignalType.INFLATION, SignalDirection.BEARISH):
                f"{series} pricing higher inflation ({delta:+.1f}c) — bullish gold/oil, bearish growth",
            (SignalType.INFLATION, SignalDirection.BULLISH):
                f"{series} pricing lower inflation ({delta:+.1f}c) — risk-on, bullish growth",
            (SignalType.GROWTH, SignalDirection.BEARISH):
                f"{series} pricing lower growth ({delta:+.1f}c) — recession signal, risk-off",
            (SignalType.GROWTH, SignalDirection.BULLISH):
                f"{series} pricing higher growth ({delta:+.1f}c) — expansion signal, risk-on",
            (SignalType.RISK_APPETITE, SignalDirection.BEARISH):
                f"{series} falling ({delta:+.1f}c) — crypto risk-off leads stocks by hours",
            (SignalType.RISK_APPETITE, SignalDirection.BULLISH):
                f"{series} rising ({delta:+.1f}c) — crypto risk-on, stocks may follow",
        }
        key = (signal_type, direction)
        return descriptions.get(key, f"{series} shifted {delta:+.1f}c ({signal_type.value})")
