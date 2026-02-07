"""
News Sentiment Fade Strategy

Markets overreact to breaking news. This strategy detects price spikes,
confirms them with volume surges, optionally uses Claude to assess
whether the reaction is overblown, then fades (trades against) the spike.

Edge:
    Behavioral overreaction. When news breaks, prediction markets spike
    on emotion/herd behavior, then revert as rational pricing takes over.
    Same principle as "gap fade" in equities.

Expected Value:
    Win rate: 55% | Avg win: 6c | Avg loss: 4c
    EV = (0.55 * 6) - (0.45 * 4) = 3.30 - 1.80 = +1.50c per contract
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import score_spread, score_volume, is_market_tradeable, get_mid_price, clamp_score
from .data_providers.news import NewsDataProvider
from .data_providers.llm import LLMProvider

logger = logging.getLogger(__name__)


class NewsSentimentFadeStrategy(Strategy):
    """
    Fade overreactions to breaking news in prediction markets.

    Configuration:
        spike_threshold_cents: Min price change to detect spike (default: 10)
        spike_window_minutes: Time window for spike detection (default: 5)
        min_volume_surge: Volume multiplier threshold (default: 2.0)
        llm_overreaction_threshold: LLM confidence to confirm (default: 0.6)
        max_hold_hours: Force exit after this (default: 4)
        enable_llm: Toggle LLM analysis (default: true)
    """

    def __init__(self, config: Dict[str, Any]):
        config.setdefault("take_profit_cents", 6)
        config.setdefault("stop_loss_cents", 4)
        super().__init__(config)

        self.spike_threshold = config.get("spike_threshold_cents", 10)
        self.spike_window_minutes = config.get("spike_window_minutes", 5)
        self.min_volume_surge = config.get("min_volume_surge", 2.0)
        self.llm_threshold = config.get("llm_overreaction_threshold", 0.6)
        self.max_hold_hours = config.get("max_hold_hours", 4)
        self.enable_llm = config.get("enable_llm", True)

        # Internal state: price + volume history per ticker
        self._price_history: Dict[str, List[Tuple[datetime, int]]] = defaultdict(list)
        self._volume_history: Dict[str, List[Tuple[datetime, int]]] = defaultdict(list)
        self._max_history = 200

        # Data providers
        self._news = NewsDataProvider()
        self._llm = LLMProvider() if self.enable_llm else None

        logger.info(
            f"NewsSentimentFadeStrategy initialized: "
            f"spike={self.spike_threshold}c/{self.spike_window_minutes}min, "
            f"volume_surge={self.min_volume_surge}x, "
            f"llm={'enabled' if self.enable_llm else 'disabled'}"
        )

    @property
    def name(self) -> str:
        return "news_sentiment_fade"

    @property
    def description(self) -> str:
        return (
            f"News sentiment fade: Detect {self.spike_threshold}c+ spikes, "
            f"fade overreactions with {self.min_volume_surge}x volume confirmation"
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

            if not is_market_tradeable(market, self.min_volume):
                continue

            if ticker in existing_positions:
                continue

            current_price = get_mid_price(market)
            volume = market.get("volume", 0) or market.get("volume_24h", 0)

            # Update histories
            self._update_history(ticker, current_price, volume, now)

            # Detect spike
            spike = self._detect_spike(ticker, now)
            if not spike:
                continue

            spike_magnitude, pre_spike_price = spike

            # Confirm volume surge
            volume_surge = self._calculate_volume_surge(ticker, now)
            if volume_surge < self.min_volume_surge:
                continue

            # Optional LLM assessment
            llm_confidence = 0.0
            if self._llm and self._llm.is_available:
                news = await self._news.find_relevant_news(
                    market.get("title", ""), max_age_hours=1
                )
                headline = news[0].title if news else "Unknown catalyst"

                analysis = await self._llm.analyze_overreaction(
                    market_title=market.get("title", ""),
                    price_before=pre_spike_price,
                    price_after=current_price,
                    news_headline=headline,
                    volume_surge=volume_surge,
                )

                if analysis.confidence >= self.llm_threshold and analysis.is_overreaction:
                    llm_confidence = analysis.confidence
                elif self.enable_llm and analysis.confidence >= self.llm_threshold:
                    # LLM says it's justified — skip
                    continue
            else:
                llm_confidence = 0.5  # Neutral when LLM unavailable

            opp = self._create_fade_opportunity(
                market=market,
                ticker=ticker,
                current_price=current_price,
                pre_spike_price=pre_spike_price,
                spike_magnitude=spike_magnitude,
                volume_surge=volume_surge,
                llm_confidence=llm_confidence,
            )

            if opp:
                opportunities.append(opp)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}] Found {len(opportunities)} fade opportunities "
            f"from {len(markets)} markets"
        )
        return opportunities

    def _update_history(
        self, ticker: str, price: int, volume: int, now: datetime
    ) -> None:
        """Update price and volume history for a ticker."""
        self._price_history[ticker].append((now, price))
        self._volume_history[ticker].append((now, volume))

        if len(self._price_history[ticker]) > self._max_history:
            self._price_history[ticker] = self._price_history[ticker][-self._max_history:]
        if len(self._volume_history[ticker]) > self._max_history:
            self._volume_history[ticker] = self._volume_history[ticker][-self._max_history:]

    def _detect_spike(
        self, ticker: str, now: datetime
    ) -> Optional[Tuple[int, int]]:
        """
        Detect if there's been a price spike in the recent window.

        Returns:
            (spike_magnitude, pre_spike_price) or None if no spike
        """
        history = self._price_history.get(ticker, [])
        if len(history) < 2:
            return None

        cutoff = now - timedelta(minutes=self.spike_window_minutes)
        recent = [(ts, p) for ts, p in history if ts >= cutoff]
        older = [(ts, p) for ts, p in history if ts < cutoff]

        if not recent or not older:
            return None

        current_price = recent[-1][1]
        pre_spike_price = older[-1][1]

        magnitude = abs(current_price - pre_spike_price)
        if magnitude >= self.spike_threshold:
            return magnitude, pre_spike_price

        return None

    def _calculate_volume_surge(self, ticker: str, now: datetime) -> float:
        """Calculate volume surge multiplier vs recent average."""
        history = self._volume_history.get(ticker, [])
        if len(history) < 3:
            return 1.0

        cutoff = now - timedelta(minutes=self.spike_window_minutes)
        recent_vols = [v for ts, v in history if ts >= cutoff]
        older_vols = [v for ts, v in history if ts < cutoff]

        if not recent_vols or not older_vols:
            return 1.0

        avg_recent = sum(recent_vols) / len(recent_vols)
        avg_older = sum(older_vols) / len(older_vols)

        if avg_older <= 0:
            return 1.0

        return avg_recent / avg_older

    def _create_fade_opportunity(
        self,
        market: Dict,
        ticker: str,
        current_price: int,
        pre_spike_price: int,
        spike_magnitude: int,
        volume_surge: float,
        llm_confidence: float,
    ) -> Optional[TradingOpportunity]:
        """Create a fade opportunity (trade against the spike)."""

        yes_bid = market.get("yes_bid", 0)
        yes_ask = market.get("yes_ask", 0)
        no_bid = market.get("no_bid", 0)
        no_ask = market.get("no_ask", 0)
        volume = market.get("volume", 0) or market.get("volume_24h", 0)

        # Fade direction: opposite of spike
        if current_price > pre_spike_price:
            # Price spiked UP — fade by buying NO
            side = "no"
            entry_price = no_ask if no_ask else (100 - current_price)
            reasoning = (
                f"Fading {spike_magnitude}c upward spike: price went "
                f"{pre_spike_price}c -> {current_price}c. "
                f"Volume surge: {volume_surge:.1f}x. "
                f"Buying NO expecting reversion."
            )
        else:
            # Price spiked DOWN — fade by buying YES
            side = "yes"
            entry_price = yes_ask if yes_ask else current_price
            reasoning = (
                f"Fading {spike_magnitude}c downward spike: price went "
                f"{pre_spike_price}c -> {current_price}c. "
                f"Volume surge: {volume_surge:.1f}x. "
                f"Buying YES expecting reversion."
            )

        # Score
        spike_score = min(spike_magnitude / 20.0, 1.0) * 30
        llm_score = llm_confidence * 30
        volume_score = min(volume_surge / 5.0, 1.0) * 20
        # Historical reversion: assume markets revert ~60% of spikes
        reversion_score = 20.0  # Constant based on market behavior

        total_score = clamp_score(spike_score + llm_score + volume_score + reversion_score)

        if total_score < self.min_score:
            return None

        return TradingOpportunity(
            ticker=ticker,
            title=market.get("title", ""),
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
                "pre_spike_price": pre_spike_price,
                "spike_magnitude": spike_magnitude,
                "volume_surge": volume_surge,
                "llm_confidence": llm_confidence,
                "entry_time": datetime.now().isoformat(),
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

        # Take profit
        if pnl_cents >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit: +{pnl_cents}c",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        # Stop loss
        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss: {pnl_cents}c",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        # Time-based exit
        entry_time_str = position.get("metadata", {}).get("entry_time")
        if entry_time_str:
            try:
                entry_time = datetime.fromisoformat(entry_time_str)
                hours_held = (datetime.now() - entry_time).total_seconds() / 3600.0
                if hours_held >= self.max_hold_hours:
                    return ExitSignal(
                        should_exit=True,
                        reason=(
                            f"Max hold time ({self.max_hold_hours}h) reached. "
                            f"P&L: {pnl_cents:+d}c"
                        ),
                        exit_type="manual",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.6,
                    )
            except (ValueError, TypeError):
                pass

        # Partial profit at 50% reversion
        pre_spike = position.get("metadata", {}).get("pre_spike_price")
        if pre_spike and pnl_cents > 0:
            spike_mag = position.get("metadata", {}).get("spike_magnitude", 0)
            if spike_mag > 0:
                reversion_pct = pnl_cents / spike_mag
                if reversion_pct >= 0.5:
                    return ExitSignal(
                        should_exit=True,
                        reason=(
                            f"50% reversion achieved: +{pnl_cents}c "
                            f"(spike was {spike_mag}c)"
                        ),
                        exit_type="take_profit",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.5,
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
        return {
            "win_rate": 0.55,
            "avg_win_cents": 6.0,
            "avg_loss_cents": 4.0,
        }

    def validate_config(self) -> tuple[bool, str]:
        valid, error = super().validate_config()
        if not valid:
            return valid, error

        if self.spike_threshold < 3:
            return False, "spike_threshold_cents must be at least 3"

        if self.spike_window_minutes < 1:
            return False, "spike_window_minutes must be at least 1"

        if self.min_volume_surge <= 1.0:
            return False, "min_volume_surge must be > 1.0"

        if self.max_hold_hours <= 0:
            return False, "max_hold_hours must be positive"

        return True, ""
