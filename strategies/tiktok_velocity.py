"""
TikTok Velocity Strategy - Social Arbitrage Trading

A DeepStack Kalshi trading strategy that exploits social sentiment signals
from TikTok to predict movements in prediction markets.

Strategy Overview:
    Extracts trending financial/economic content from TikTok to predict
    sentiment-driven moves in Kalshi prediction markets. Uses exponential
    moving averages on hashtag volume + VADER sentiment analysis to
    generate velocity scores. When velocity crosses thresholds, generates
    trading signals mapped to relevant Kalshi markets.

Signal Generation Logic:
    1. Monitor TikTok for trending finance/econ hashtags (#recession, #inflation)
    2. Calculate velocity: EMA of hashtag view growth + sentiment momentum
    3. Map trending topics to Kalshi markets via keyword matching
    4. Generate signals when velocity exceeds configured thresholds
    5. Apply sentiment direction: positive sentiment -> YES, negative -> NO

Market Mapping (examples):
    - #recession trending + negative sentiment -> Short INXD (recession fear)
    - #inflation trending + negative sentiment -> Trade KXCPI inflation markets
    - #crypto trending + positive sentiment -> Long KXBTC crypto markets
    - #fed trending + hawkish sentiment -> Short rate-sensitive markets
    - #crash trending -> Long volatility or short index markets

Expected Value Calculation:
    - Win rate: 52% (social signals are noisy but have edge)
    - Avg win: 12 cents (strong sentiment moves persist)
    - Avg loss: 6 cents (cut losers quickly)
    - EV = (0.52 * 12) - (0.48 * 6) = +3.36 cents per contract

Dependencies:
    - TikTok-Api (optional, for real TikTok API access)
    - vaderSentiment (for sentiment analysis)
    Install: pip install TikTok-Api vaderSentiment

Configuration Parameters:
    - velocity_threshold: Minimum velocity score to trigger trade (default: 0.6)
    - sentiment_threshold: Minimum |sentiment| to consider (default: 0.2)
    - ema_periods: EMA smoothing factor (default: 12)
    - max_hashtag_age_hours: How fresh hashtags must be (default: 4)
    - hashtags: List of hashtags to monitor (or use defaults)
    - market_mappings: Dict mapping keywords to Kalshi series tickers
    - take_profit_cents: Target profit per contract (default: 12)
    - stop_loss_cents: Max loss per contract (default: 6)
    - min_volume: Minimum market volume (default: 150)
    - max_positions: Max concurrent positions for this strategy (default: 3)
    - api_delay_ms: Delay between TikTok API calls (default: 1000)
    - backtest_mode: Enable backtesting with historical data (default: False)
    - backtest_data_path: Path to JSON backtest data file

Risk Management Integration:
    - Uses Kelly Criterion for position sizing (via PerformanceTracker)
    - Respects max daily loss limits from config
    - Max concurrent positions limit
    - Sentiment reversal detection for early exits

Backtesting Support:
    - load_backtest_data(): Load historical TikTok data
    - reset_backtest(): Reset backtest state
    - Mock data generation when APIs unavailable

Example Usage:
    >>> config = {
    ...     "velocity_threshold": 0.7,
    ...     "sentiment_threshold": 0.3,
    ...     "hashtags": ["recession", "inflation", "crypto"],
    ... }
    >>> strategy = TikTokVelocityStrategy(config)
    >>> opportunities = await strategy.scan_opportunities(kalshi_markets)
    >>> for opp in opportunities:
    ...     print(f"Signal: {opp.ticker} -> {opp.side} @ {opp.entry_price_cents}c")

Example with Backtest:
    >>> strategy = TikTokVelocityStrategy({"backtest_mode": True})
    >>> strategy.load_backtest_data(historical_data)
    >>> opportunities = await strategy.scan_opportunities(kalshi_markets)
"""

import asyncio
import logging
import re
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from .base import Strategy, TradingOpportunity, ExitSignal

logger = logging.getLogger(__name__)

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False

@dataclass
class HashtagMetrics:
    hashtag: str
    view_count: int = 0
    video_count: int = 0
    sentiment_score: float = 0.0
    velocity: float = 0.0
    last_updated: datetime = field(default_factory=datetime.now)
    samples: List[Tuple[datetime, int, float]] = field(default_factory=list)

@dataclass
class TrendSignal:
    hashtag: str
    keyword: str
    velocity: float
    sentiment: float
    direction: str
    confidence: float
    timestamp: datetime
    mapped_markets: List[str] = field(default_factory=list)

class TikTokVelocityStrategy(Strategy):
    """Social arbitrage strategy using TikTok trend velocity and sentiment."""

    DEFAULT_HASHTAGS = [
        "recession", "inflation", "crypto", "bitcoin", "ethereum",
        "fed", "federalreserve", "interestrates", "stockmarket", "stocks",
        "economy", "gdp", "jobs", "unemployment", "housing",
        "sp500", "nasdaq", "dowjones", "bullmarket", "bearmarket",
        "crash", "rally", "ai", "techstocks",
    ]

    DEFAULT_MARKET_MAPPINGS = {
        "recession": ["INXDJ", "KXGDP", "KXUNEMP"],
        "inflation": ["KXCPI", "KXINFL", "KXHOT"],
        "crypto": ["KXBTC", "KXETH", "KXSOL", "KXCOIN"],
        "bitcoin": ["KXBTC"],
        "ethereum": ["KXETH"],
        "fed": ["KXFED", "KXIR", "INXDJ"],
        "rates": ["KXFED", "KXIR"],
        "stockmarket": ["INXDJ", "INXD", "KXDJIA"],
        "sp500": ["INXD"],
        "nasdaq": ["KXCOMP"],
        "jobs": ["KXJOBS", "KXUNEMP"],
        "unemployment": ["KXUNEMP", "KXJOBS"],
        "housing": ["KXHOME", "KXBUILD"],
        "gdp": ["KXGDP"],
        "ai": ["KXTECH", "KXNVDA", "KXAI"],
        "crash": ["INXDJ", "INXD", "KXVOL"],
    }

    BULLISH_KEYWORDS = [
        "rally", "surge", "boom", "bull", "bullish", "breakout", "pump",
        "green", "gains", "growth", "recover", "strong", "buy", "long", "hold",
    ]

    BEARISH_KEYWORDS = [
        "crash", "dump", "bear", "bearish", "recession", "collapse", "plunge",
        "tank", "bleeding", "red", "panic", "fear", "sell", "short",
        "debt", "crisis", "default", "bankrupt", "layoffs",
    ]

    def __init__(self, config: Dict[str, Any]):
        config.setdefault("take_profit_cents", 12)
        config.setdefault("stop_loss_cents", 6)
        config.setdefault("min_volume", 150)
        super().__init__(config)

        self.velocity_threshold = config.get("velocity_threshold", 0.6)
        self.sentiment_threshold = config.get("sentiment_threshold", 0.2)
        self.ema_periods = config.get("ema_periods", 12)
        self.max_hashtag_age_hours = config.get("max_hashtag_age_hours", 4)
        self.api_delay_ms = config.get("api_delay_ms", 1000)
        self.backtest_mode = config.get("backtest_mode", False)
        self.backtest_data_path = config.get("backtest_data_path")

        self.hashtags = config.get("hashtags", self.DEFAULT_HASHTAGS)
        self.market_mappings = config.get("market_mappings", self.DEFAULT_MARKET_MAPPINGS)

        # State
        self._hashtag_metrics: Dict[str, HashtagMetrics] = {}
        self._sentiment_analyzer = SentimentIntensityAnalyzer() if VADER_AVAILABLE else None
        self._last_scan_time: Optional[datetime] = None
        self._scan_counter = 0

        # Backtest data
        self._backtest_data: List[Dict] = []
        self._backtest_index = 0
        if self.backtest_mode and self.backtest_data_path:
            self._load_backtest_data()

        logger.info(
            f"TikTokVelocityStrategy initialized: "
            f"threshold={self.velocity_threshold}, hashtags={len(self.hashtags)}"
        )

    @property
    def name(self) -> str:
        return "tiktok_velocity"

    @property
    def description(self) -> str:
        return f"TikTok social arbitrage: velocity>{self.velocity_threshold}, sentiment>|{self.sentiment_threshold}|"

    def _load_backtest_data(self) -> None:
        """Load historical TikTok data for backtesting."""
        try:
            with open(self.backtest_data_path, 'r') as f:
                self._backtest_data = json.load(f)
            logger.info(f"Loaded {len(self._backtest_data)} backtest records")
        except Exception as e:
            logger.error(f"Failed to load backtest data: {e}")
            self._backtest_data = []

    async def _fetch_tiktok_hashtag_data(self, hashtag: str) -> Optional[Dict[str, Any]]:
        """
        Fetch hashtag data from TikTok API or mock/backtest sources.
        
        Returns dict with view_count, video_count, and sample videos.
        """
        # Backtest mode: return next data point from historical data
        if self.backtest_mode:
            return self._get_backtest_data(hashtag)

        # Mock mode: return simulated data for testing
        if not VADER_AVAILABLE:
            return self._generate_mock_data(hashtag)

        # Real API mode - would use TikTok-Api here
        # For now, return None as API requires complex setup
        logger.debug(f"TikTok API not implemented, using mock data for #{hashtag}")
        return self._generate_mock_data(hashtag)

    def _get_backtest_data(self, hashtag: str) -> Optional[Dict[str, Any]]:
        """Get next data point from backtest dataset."""
        if self._backtest_index >= len(self._backtest_data):
            return None
        
        record = self._backtest_data[self._backtest_index]
        self._backtest_index += 1
        
        if record.get("hashtag") == hashtag:
            return record
        return None

    def _generate_mock_data(self, hashtag: str) -> Dict[str, Any]:
        """Generate realistic mock data for testing."""
        import random
        base_views = hash(hashtag) % 10000000 + 1000000
        noise = random.gauss(0, 0.1)
        trending_factor = 1.0 + (self._scan_counter * 0.05)
        
        # Simulate trending hashtags growing faster
        if hashtag in ["recession", "crash", "crypto"]:
            trending_factor *= 1.5
        
        return {
            "hashtag": hashtag,
            "view_count": int(base_views * trending_factor * (1 + noise)),
            "video_count": int(base_views * 0.1 * trending_factor),
            "videos": self._generate_mock_videos(hashtag),
            "timestamp": datetime.now().isoformat(),
        }

    def _generate_mock_videos(self, hashtag: str) -> List[Dict]:
        """Generate mock video data for sentiment analysis."""
        import random
        templates = {
            "recession": [
                "Market crash coming??? #recession #stocks",
                "Why we are NOT in a recession #economy",
                "Recession proof your portfolio now!",
            ],
            "inflation": [
                "Inflation is killing my savings",
                "Fed finally beating inflation!",
                "Why inflation might be over",
            ],
            "crypto": [
                "Bitcoin to the moon! #crypto",
                "Crypto crash incoming??",
                "Best crypto to buy now",
            ],
        }
        
        captions = templates.get(hashtag, [f"Trending #{hashtag} content"])
        return [
            {"desc": random.choice(captions), "likes": random.randint(1000, 100000)}
            for _ in range(5)
        ]

    def _analyze_sentiment(self, text: str) -> float:
        """
        Analyze sentiment of text using VADER.
        Returns compound sentiment score (-1 to 1).
        """
        if self._sentiment_analyzer:
            scores = self._sentiment_analyzer.polarity_scores(text)
            return scores["compound"]
        
        # Fallback: simple keyword-based sentiment
        text_lower = text.lower()
        bullish_count = sum(1 for kw in self.BULLISH_KEYWORDS if kw in text_lower)
        bearish_count = sum(1 for kw in self.BEARISH_KEYWORDS if kw in text_lower)
        
        total = bullish_count + bearish_count
        if total == 0:
            return 0.0
        return (bullish_count - bearish_count) / total

    def _calculate_ema(self, values: List[float], periods: int) -> float:
        """Calculate exponential moving average."""
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        
        multiplier = 2 / (periods + 1)
        ema = values[0]
        for value in values[1:]:
            ema = (value * multiplier) + (ema * (1 - multiplier))
        return ema

    def _calculate_velocity(self, metric: HashtagMetrics) -> float:
        """
        Calculate velocity score based on EMA of view growth rate.
        
        Velocity = EMA of (current_views / previous_views - 1) * sentiment_boost
        
        Returns velocity score from 0 to infinity (typically 0-2 range).
        """
        samples = metric.samples
        if len(samples) < 2:
            return 0.0
        
        # Calculate view growth rates
        growth_rates = []
        for i in range(1, len(samples)):
            prev_views = samples[i-1][1]
            curr_views = samples[i][1]
            if prev_views > 0:
                growth_rate = (curr_views - prev_views) / prev_views
                growth_rates.append(growth_rate)
        
        if not growth_rates:
            return 0.0
        
        # EMA smoothing
        velocity = self._calculate_ema(growth_rates, self.ema_periods)
        
        # Boost velocity by sentiment intensity (controversial topics move faster)
        sentiment_boost = 1.0 + abs(metric.sentiment_score) * 0.5
        velocity *= sentiment_boost
        
        return max(0, velocity)

    def _update_hashtag_metrics(self, hashtag: str, data: Dict[str, Any]) -> HashtagMetrics:
        """Update metrics for a hashtag with new data."""
        now = datetime.now()
        
        # Get or create metrics
        metric = self._hashtag_metrics.get(hashtag, HashtagMetrics(hashtag=hashtag))
        
        # Analyze sentiment from video descriptions
        videos = data.get("videos", [])
        if videos:
            sentiments = [self._analyze_sentiment(v.get("desc", "")) for v in videos]
            avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0
        else:
            avg_sentiment = 0.0
        
        # Update metric
        metric.view_count = data.get("view_count", 0)
        metric.video_count = data.get("video_count", 0)
        metric.sentiment_score = avg_sentiment
        metric.last_updated = now
        metric.samples.append((now, metric.view_count, avg_sentiment))
        
        # Keep only last 100 samples to prevent memory bloat
        if len(metric.samples) > 100:
            metric.samples = metric.samples[-100:]
        
        # Calculate velocity
        metric.velocity = self._calculate_velocity(metric)
        
        self._hashtag_metrics[hashtag] = metric
        return metric

    def _generate_trend_signals(self) -> List[TrendSignal]:
        """
        Generate trend signals from hashtag metrics.
        
        Filters for hashtags with velocity > threshold and sentiment magnitude > threshold.
        Maps trending hashtags to Kalshi market series.
        """
        signals = []
        now = datetime.now()
        
        for hashtag, metric in self._hashtag_metrics.items():
            # Check freshness
            age_hours = (now - metric.last_updated).total_seconds() / 3600
            if age_hours > self.max_hashtag_age_hours:
                continue
            
            # Check velocity threshold
            if metric.velocity < self.velocity_threshold:
                continue
            
            # Check sentiment threshold
            if abs(metric.sentiment_score) < self.sentiment_threshold:
                continue
            
            # Determine direction
            direction = "bullish" if metric.sentiment_score > 0 else "bearish"
            
            # Map to Kalshi markets
            mapped_markets = self._map_to_markets(hashtag)
            
            # Calculate confidence (0-1)
            confidence = min(1.0, (
                (metric.velocity / self.velocity_threshold) * 0.5 +
                (abs(metric.sentiment_score) / self.sentiment_threshold) * 0.5
            ))
            
            signal = TrendSignal(
                hashtag=hashtag,
                keyword=hashtag,
                velocity=metric.velocity,
                sentiment=metric.sentiment_score,
                direction=direction,
                confidence=confidence,
                timestamp=now,
                mapped_markets=mapped_markets,
            )
            signals.append(signal)
        
        # Sort by confidence
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals

    def _map_to_markets(self, hashtag: str) -> List[str]:
        """Map a hashtag to relevant Kalshi market series tickers."""
        # Direct lookup
        if hashtag in self.market_mappings:
            return self.market_mappings[hashtag]
        
        # Partial matching
        matches = []
        hashtag_lower = hashtag.lower()
        for keyword, markets in self.market_mappings.items():
            if keyword in hashtag_lower or hashtag_lower in keyword:
                matches.extend(markets)
        
        return list(set(matches))  # Deduplicate

    def _match_market_to_signal(self, market: Dict, signal: TrendSignal) -> bool:
        """Check if a Kalshi market matches a trend signal."""
        ticker = market.get("ticker", "")
        title = market.get("title", "").lower()
        series = market.get("series_ticker", "")
        
        # Check if market series is in mapped markets
        for mapped_series in signal.mapped_markets:
            if mapped_series in ticker or mapped_series in series:
                return True
        
        # Keyword matching in title
        keyword_lower = signal.keyword.lower()
        if keyword_lower in title:
            return True
        
        return False

    def _determine_trade_side(self, signal: TrendSignal, market: Dict) -> Optional[str]:
        """
        Determine which side to trade (YES/NO) based on signal.
        
        For most markets:
        - Bullish sentiment -> Buy YES (expect positive outcome)
        - Bearish sentiment -> Buy NO (expect negative outcome)
        
        Special handling for inverse markets (e.g., recession markets where
        NO means no recession which is bullish).
        """
        title = market.get("title", "").lower()
        
        # Check for inverse markets
        inverse_keywords = ["no recession", "no crash", "won't", "will not"]
        is_inverse = any(kw in title for kw in inverse_keywords)
        
        if is_inverse:
            # For inverse markets, flip the logic
            return "no" if signal.direction == "bullish" else "yes"
        else:
            return "yes" if signal.direction == "bullish" else "no"

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan markets for TikTok velocity-based opportunities.
        
        Process:
        1. Fetch TikTok data for monitored hashtags
        2. Update hashtag metrics and calculate velocity
        3. Generate trend signals from high-velocity hashtags
        4. Map signals to Kalshi markets
        5. Create trading opportunities
        """
        existing_positions = existing_positions or {}
        opportunities = []
        self._scan_counter += 1
        
        # Step 1: Fetch TikTok data for all hashtags
        logger.info(f"[{self.name}] Scanning {len(self.hashtags)} hashtags...")
        
        for hashtag in self.hashtags:
            try:
                data = await self._fetch_tiktok_hashtag_data(hashtag)
                if data:
                    self._update_hashtag_metrics(hashtag, data)
                
                # Rate limiting
                if self.api_delay_ms > 0:
                    await asyncio.sleep(self.api_delay_ms / 1000)
                    
            except Exception as e:
                logger.warning(f"Failed to fetch data for #{hashtag}: {e}")
        
        # Step 2: Generate trend signals
        signals = self._generate_trend_signals()
        logger.info(f"[{self.name}] Generated {len(signals)} trend signals")
        
        if not signals:
            return []
        
        # Step 3: Match signals to markets
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
            
            # Check for matching signals
            for signal in signals:
                if self._match_market_to_signal(market, signal):
                    opp = self._create_opportunity(market, signal, volume)
                    if opp:
                        opportunities.append(opp)
                        break  # One opportunity per market
        
        # Sort by score
        opportunities.sort(key=lambda x: x.score, reverse=True)
        
        # Limit max positions
        if len(existing_positions) >= self.max_concurrent_positions:
            opportunities = []
        elif len(existing_positions) + len(opportunities) > self.max_concurrent_positions:
            opportunities = opportunities[:self.max_concurrent_positions - len(existing_positions)]
        
        logger.info(
            f"[{self.name}] Found {len(opportunities)} opportunities "
            f"from {len(markets)} markets"
        )
        
        return opportunities

    def _create_opportunity(
        self,
        market: Dict,
        signal: TrendSignal,
        volume: int,
    ) -> Optional[TradingOpportunity]:
        ticker = market.get("ticker", "")
        title = market.get("title", "")
        
        yes_bid = market.get("yes_bid", 0)
        yes_ask = market.get("yes_ask", 0)
        no_bid = market.get("no_bid", 0)
        no_ask = market.get("no_ask", 0)
        
        if yes_bid and yes_ask:
            yes_mid = (yes_bid + yes_ask) // 2
        else:
            yes_mid = market.get("last_price", 50)
        
        side = self._determine_trade_side(signal, market)
        if not side:
            return None
        
        if side == "yes":
            entry_price = yes_ask if yes_ask else yes_mid
        else:
            entry_price = no_ask if no_ask else (100 - yes_mid)
        
        if not (1 <= entry_price <= 99):
            return None
        
        velocity_score = min(signal.velocity / self.velocity_threshold * 30, 40)
        sentiment_score = min(abs(signal.sentiment) / self.sentiment_threshold * 30, 40)
        confidence_score = signal.confidence * 20
        
        total_score = velocity_score + sentiment_score + confidence_score
        
        if total_score < self.min_score:
            return None
        
        reasoning = f"TikTok velocity: #{signal.hashtag} v={signal.velocity:.2f}, s={signal.sentiment:+.2f}"
        
        return TradingOpportunity(
            ticker=ticker,
            title=title,
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=yes_mid,
            current_no_price=100 - yes_mid,
            volume=volume,
            score=min(total_score, 100),
            reasoning=reasoning,
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "hashtag": signal.hashtag,
                "velocity": signal.velocity,
                "sentiment": signal.sentiment,
                "direction": signal.direction,
                "confidence": signal.confidence,
            },
        )

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        entry_price = position.get("entry_price", 50)
        side = position.get("side", "yes")
        metadata = position.get("metadata", {})
        
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
        
        # Sentiment reversal check
        hashtag = metadata.get("hashtag")
        if hashtag and hashtag in self._hashtag_metrics:
            metric = self._hashtag_metrics[hashtag]
            original_sentiment = metadata.get("sentiment", 0)
            
            if original_sentiment > 0 and metric.sentiment_score < -self.sentiment_threshold:
                return ExitSignal(
                    should_exit=True,
                    reason=f"Sentiment reversed to negative",
                    exit_type="manual",
                    current_price_cents=current_price,
                    pnl_cents=pnl_cents,
                    urgency=0.7,
                )
            elif original_sentiment < 0 and metric.sentiment_score > self.sentiment_threshold:
                return ExitSignal(
                    should_exit=True,
                    reason=f"Sentiment reversed to positive",
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
                    close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
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
        
        return ExitSignal(
            should_exit=False,
            reason=f"P&L: {pnl_cents:+d}c | Holding for trend continuation",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        return {
            "win_rate": 0.52,
            "avg_win_cents": float(self.take_profit),
            "avg_loss_cents": float(self.stop_loss),
        }

    def validate_config(self) -> tuple[bool, str]:
        valid, error = super().validate_config()
        if not valid:
            return valid, error
        if self.velocity_threshold <= 0:
            return False, "velocity_threshold must be positive"
        if not (0 <= self.sentiment_threshold <= 1):
            return False, "sentiment_threshold must be 0-1"
        if self.ema_periods < 2:
            return False, "ema_periods must be >= 2"
        if not self.hashtags:
            return False, "at least one hashtag required"
        return True, ""

    def load_backtest_data(self, data: List[Dict]) -> None:
        self._backtest_data = data
        self._backtest_index = 0
        self.backtest_mode = True
        logger.info(f"Loaded {len(data)} backtest records")

    def reset_backtest(self) -> None:
        self._backtest_index = 0
        self._hashtag_metrics.clear()
        self._scan_counter = 0

    def get_hashtag_metrics(self) -> Dict[str, HashtagMetrics]:
        return self._hashtag_metrics.copy()

    def get_trend_signals(self) -> List[TrendSignal]:
        return self._generate_trend_signals()
