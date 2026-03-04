"""
Market Governor — Self-Governance Brain for DeepStack

Proactive intelligence layer that detects market regimes and routes
strategies accordingly. Sits between existing safety layers and the
trading loop — never overrides circuit breakers or daily limits.

Architecture:
    GovernanceEngine (orchestrator)
      |-- RegimeDetector    (what are conditions NOW?)
      |-- StrategyRouter    (which strategies fit these conditions?)  [Phase 2]
      |-- BleedDetector     (are we slowly losing money?)            [Phase 2]
      |-- CycleAnalyzer     (what will conditions be TOMORROW?)      [Phase 3]
"""

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


@contextmanager
def _db_connection(
    db_path: Path, wal: bool = False
) -> Generator[sqlite3.Connection, None, None]:
    """Open a SQLite connection with consistent timeout and optional WAL mode.

    Commits on success, rolls back on error, always closes the connection.
    """
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class MarketRegime(Enum):
    """Market condition classification derived from Kalshi data."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOL_CHOPPY = "high_vol_choppy"
    LOW_VOL_CALM = "low_vol_calm"


@dataclass
class RegimeSnapshot:
    """Point-in-time regime assessment with underlying factors."""

    regime: MarketRegime
    confidence: float  # 0.0-1.0
    timestamp: datetime
    volatility: float  # Normalized 0.0-1.0
    trend_strength: float  # -1.0 to 1.0
    mean_reversion_score: float  # 0.0-1.0
    volume_ratio: float  # Current / 24h average
    num_markets_sampled: int
    raw_factors: Dict[str, float] = field(default_factory=dict)


@dataclass
class GovernanceDecision:
    """Record of a governance action for audit trail."""

    timestamp: datetime
    regime: MarketRegime
    regime_confidence: float
    action: str  # "enable", "disable", "hold", "advisory"
    strategy_name: Optional[str]
    reason: str
    mode: str  # "advisory", "autonomous", "manual"


@dataclass
class MarketSnapshot:
    """Simplified market data point for regime computation."""

    timestamp: datetime
    ticker: str
    yes_price: float  # 0-100 cents
    volume: int
    open_interest: Optional[int] = None


@dataclass
class RegimePrediction:
    """Predicted future regime with confidence."""

    predicted_regime: MarketRegime
    confidence: float  # 0.0-1.0
    factors: Dict[str, Any] = field(default_factory=dict)


class RegimeDetector:
    """
    Classifies current market conditions into a regime using Kalshi data.

    Computes 4 factors from a rolling window of market snapshots:
    1. Volatility — normalized price range across active markets
    2. Trend strength — directional consensus (-1.0 to 1.0)
    3. Mean-reversion score — zero-crossing rate of price deviations
    4. Volume ratio — current vs 24h average volume

    Requires minimum 5 snapshots before classifying (cold start returns
    LOW_VOL_CALM with low confidence).
    """

    MIN_SNAPSHOTS = 5

    def __init__(self, lookback_periods: int = 20):
        self.lookback_periods = lookback_periods
        self._snapshots: List[List[MarketSnapshot]] = []

    def add_snapshot(self, markets: List[MarketSnapshot]) -> None:
        """Add a batch of market snapshots (one per trading cycle)."""
        self._snapshots.append(markets)
        if len(self._snapshots) > self.lookback_periods:
            self._snapshots = self._snapshots[-self.lookback_periods:]

    def detect(self) -> RegimeSnapshot:
        """Classify current market regime from accumulated snapshots."""
        now = datetime.now(timezone.utc)

        if len(self._snapshots) < self.MIN_SNAPSHOTS:
            return RegimeSnapshot(
                regime=MarketRegime.LOW_VOL_CALM,
                confidence=0.1,
                timestamp=now,
                volatility=0.0,
                trend_strength=0.0,
                mean_reversion_score=0.0,
                volume_ratio=1.0,
                num_markets_sampled=0,
            )

        volatility = self._compute_volatility()
        trend_strength = self._compute_trend_strength()
        mean_reversion = self._compute_mean_reversion_score()
        volume_ratio = self._compute_volume_ratio()

        total_markets = sum(len(s) for s in self._snapshots)

        regime, confidence = self._classify(
            volatility, trend_strength, mean_reversion, volume_ratio
        )

        return RegimeSnapshot(
            regime=regime,
            confidence=confidence,
            timestamp=now,
            volatility=volatility,
            trend_strength=trend_strength,
            mean_reversion_score=mean_reversion,
            volume_ratio=volume_ratio,
            num_markets_sampled=total_markets,
            raw_factors={
                "volatility": volatility,
                "trend_strength": trend_strength,
                "mean_reversion_score": mean_reversion,
                "volume_ratio": volume_ratio,
                "num_snapshots": len(self._snapshots),
            },
        )

    def _compute_volatility(self) -> float:
        """Normalized price range (high-low)/mean across active markets."""
        if not self._snapshots:
            return 0.0

        # Collect all prices per ticker across time
        ticker_prices: Dict[str, List[float]] = {}
        for batch in self._snapshots:
            for m in batch:
                ticker_prices.setdefault(m.ticker, []).append(m.yes_price)

        if not ticker_prices:
            return 0.0

        ranges = []
        for prices in ticker_prices.values():
            if len(prices) < 2:
                continue
            price_range = max(prices) - min(prices)
            mean_price = sum(prices) / len(prices)
            if mean_price > 0:
                ranges.append(price_range / mean_price)

        if not ranges:
            return 0.0

        raw = sum(ranges) / len(ranges)
        # Normalize: typical range 0-0.5 maps to 0-1
        return min(raw / 0.5, 1.0)

    def _compute_trend_strength(self) -> float:
        """Proportion of markets moving consistently in one direction."""
        if len(self._snapshots) < 2:
            return 0.0

        # Compare first half vs second half mean prices per ticker
        mid = len(self._snapshots) // 2
        first_half = self._snapshots[:mid]
        second_half = self._snapshots[mid:]

        def mean_prices(batches: List[List[MarketSnapshot]]) -> Dict[str, float]:
            totals: Dict[str, List[float]] = {}
            for batch in batches:
                for m in batch:
                    totals.setdefault(m.ticker, []).append(m.yes_price)
            return {t: sum(ps) / len(ps) for t, ps in totals.items() if ps}

        first_means = mean_prices(first_half)
        second_means = mean_prices(second_half)

        common_tickers = set(first_means) & set(second_means)
        if not common_tickers:
            return 0.0

        up_count = 0
        down_count = 0
        for ticker in common_tickers:
            diff = second_means[ticker] - first_means[ticker]
            if diff > 0.5:  # Half-cent threshold
                up_count += 1
            elif diff < -0.5:
                down_count += 1

        total = len(common_tickers)
        if total == 0:
            return 0.0

        # Positive = trending up, negative = trending down
        return (up_count - down_count) / total

    def _compute_mean_reversion_score(self) -> float:
        """Zero-crossing rate of price deviations from rolling mean."""
        if len(self._snapshots) < 3:
            return 0.0

        # Flatten into per-ticker time series
        ticker_series: Dict[str, List[float]] = {}
        for batch in self._snapshots:
            for m in batch:
                ticker_series.setdefault(m.ticker, []).append(m.yes_price)

        crossing_rates = []
        for prices in ticker_series.values():
            if len(prices) < 3:
                continue
            mean_price = sum(prices) / len(prices)
            deviations = [p - mean_price for p in prices]

            crossings = 0
            for i in range(1, len(deviations)):
                if deviations[i - 1] * deviations[i] < 0:
                    crossings += 1

            max_crossings = len(deviations) - 1
            if max_crossings > 0:
                crossing_rates.append(crossings / max_crossings)

        if not crossing_rates:
            return 0.0

        return sum(crossing_rates) / len(crossing_rates)

    def _compute_volume_ratio(self) -> float:
        """Current volume vs rolling average volume."""
        if len(self._snapshots) < 2:
            return 1.0

        # Current = last batch, historical = all prior
        current_vols = [m.volume for m in self._snapshots[-1]]
        historical_vols = [
            m.volume for batch in self._snapshots[:-1] for m in batch
        ]

        if not current_vols or not historical_vols:
            return 1.0

        current_avg = sum(current_vols) / len(current_vols)
        historical_avg = sum(historical_vols) / len(historical_vols)

        if historical_avg == 0:
            return 1.0

        return current_avg / historical_avg

    def _classify(
        self,
        volatility: float,
        trend_strength: float,
        mean_reversion: float,
        volume_ratio: float,
    ) -> Tuple[MarketRegime, float]:
        """Map factor values to regime classification with confidence."""
        abs_trend = abs(trend_strength)

        # High volatility + no clear trend = choppy
        if volatility > 0.7 and abs_trend < 0.4:
            confidence = min(volatility, 1.0) * 0.8
            return MarketRegime.HIGH_VOL_CHOPPY, confidence

        # Strong mean reversion + moderate volatility
        if mean_reversion > 0.6 and abs_trend < 0.4:
            confidence = mean_reversion * 0.85
            return MarketRegime.MEAN_REVERTING, confidence

        # Clear directional trend
        if abs_trend > 0.4 and mean_reversion < 0.6:
            confidence = abs_trend * 0.9
            if trend_strength > 0:
                return MarketRegime.TRENDING_UP, confidence
            else:
                return MarketRegime.TRENDING_DOWN, confidence

        # Low volatility, no trend = calm
        if volatility < 0.3 and abs_trend < 0.4:
            confidence = (1.0 - volatility) * 0.7
            return MarketRegime.LOW_VOL_CALM, confidence

        # Ambiguous — default to calm with low confidence
        return MarketRegime.LOW_VOL_CALM, 0.3


@dataclass
class BleedSignal:
    """Result of bleed detection for a strategy or portfolio."""

    strategy_name: Optional[str]  # None = portfolio-level
    classification: str  # "slow_bleed", "sharp_loss", "normal"
    cumulative_pnl_cents: float
    slope_cents_per_hour: float
    window_hours: int


class StrategyRouter:
    """
    Maps strategy x regime to performance fitness scores.

    Uses Bayesian blending of prior expectations with observed trade
    outcomes per regime. Same epistemology as PerformanceTracker.

    Default priors encode domain knowledge about which strategies
    should perform well in each market condition.
    """

    # Default fitness priors: {strategy_name: {regime: prior_fitness}}
    # 1.0 = expected to thrive, 0.0 = expected to fail
    DEFAULT_PRIORS: Dict[str, Dict[str, float]] = {
        "mean_reversion": {
            "trending_up": 0.3, "trending_down": 0.3,
            "mean_reverting": 0.9, "high_vol_choppy": 0.4, "low_vol_calm": 0.6,
        },
        "momentum": {
            "trending_up": 0.85, "trending_down": 0.85,
            "mean_reverting": 0.2, "high_vol_choppy": 0.3, "low_vol_calm": 0.3,
        },
        "combinatorial_arbitrage": {
            "trending_up": 0.6, "trending_down": 0.6,
            "mean_reverting": 0.7, "high_vol_choppy": 0.5, "low_vol_calm": 0.5,
        },
        "cross_platform_arbitrage": {
            "trending_up": 0.7, "trending_down": 0.7,
            "mean_reverting": 0.6, "high_vol_choppy": 0.8, "low_vol_calm": 0.4,
        },
        "high_probability_bonds": {
            "trending_up": 0.5, "trending_down": 0.4,
            "mean_reverting": 0.6, "high_vol_choppy": 0.3, "low_vol_calm": 0.8,
        },
        "calibration_edge": {
            "trending_up": 0.5, "trending_down": 0.5,
            "mean_reverting": 0.6, "high_vol_choppy": 0.7, "low_vol_calm": 0.5,
        },
        "weather_aggregation": {
            "trending_up": 0.5, "trending_down": 0.5,
            "mean_reverting": 0.5, "high_vol_choppy": 0.5, "low_vol_calm": 0.5,
        },
        "news_sentiment_fade": {
            "trending_up": 0.4, "trending_down": 0.4,
            "mean_reverting": 0.5, "high_vol_choppy": 0.8, "low_vol_calm": 0.3,
        },
        "correlated_event_arbitrage": {
            "trending_up": 0.6, "trending_down": 0.6,
            "mean_reverting": 0.6, "high_vol_choppy": 0.7, "low_vol_calm": 0.5,
        },
        "domain_specialization": {
            "trending_up": 0.6, "trending_down": 0.6,
            "mean_reverting": 0.5, "high_vol_choppy": 0.5, "low_vol_calm": 0.5,
        },
        "crypto_intraday": {
            "trending_up": 0.8, "trending_down": 0.7,
            "mean_reverting": 0.4, "high_vol_choppy": 0.6, "low_vol_calm": 0.3,
        },
        "bear_macro": {
            "trending_up": 0.3, "trending_down": 0.8,
            "mean_reverting": 0.4, "high_vol_choppy": 0.5, "low_vol_calm": 0.4,
        },
        "settlement_betting": {
            "trending_up": 0.4, "trending_down": 0.4,
            "mean_reverting": 0.7, "high_vol_choppy": 0.3, "low_vol_calm": 0.8,
        },
        "tv_signals": {
            "trending_up": 0.6, "trending_down": 0.6,
            "mean_reverting": 0.5, "high_vol_choppy": 0.5, "low_vol_calm": 0.5,
        },
    }

    def __init__(
        self,
        db_path: str,
        prior_strength: int = 5,
        enable_threshold: float = 0.5,
        disable_threshold: float = 0.3,
        max_strategies_disabled_pct: float = 0.75,
    ):
        self.db_path = Path(db_path).expanduser()
        self.prior_strength = prior_strength
        self.enable_threshold = enable_threshold
        self.disable_threshold = disable_threshold
        self.max_strategies_disabled_pct = max_strategies_disabled_pct

        # In-memory fitness cache: {(strategy, regime): (fitness, trade_count)}
        self._fitness_cache: Dict[Tuple[str, str], Tuple[float, int]] = {}
        self._load_fitness_from_db()

    def _load_fitness_from_db(self) -> None:
        """Load existing fitness scores from SQLite."""
        try:
            with _db_connection(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT strategy_name, regime, fitness_score, trade_count "
                    "FROM strategy_regime_fitness"
                ).fetchall()
            for name, regime, fitness, count in rows:
                self._fitness_cache[(name, regime)] = (fitness, count)
        except Exception:
            pass  # Table may not exist yet on first run

    def get_fitness(self, strategy_name: str, regime: MarketRegime) -> float:
        """Get blended fitness score for a strategy in a regime."""
        regime_val = regime.value
        cached = self._fitness_cache.get((strategy_name, regime_val))

        # Get prior
        prior = self.DEFAULT_PRIORS.get(strategy_name, {}).get(regime_val, 0.5)

        if cached is None:
            return prior

        observed, n = cached
        k = self.prior_strength
        # Bayesian blending: same formula as PerformanceTracker
        blended = (k * prior + n * observed) / (k + n)
        return blended

    def record_trade_outcome(
        self, strategy_name: str, regime: MarketRegime, pnl_cents: float
    ) -> None:
        """Update fitness for a strategy in the current regime after a trade closes."""
        regime_val = regime.value
        key = (strategy_name, regime_val)

        # Get existing or start fresh
        current_fitness, current_count = self._fitness_cache.get(key, (0.5, 0))
        new_count = current_count + 1

        # Win = 1.0, loss = 0.0, break-even = 0.5
        outcome = 1.0 if pnl_cents > 0 else (0.0 if pnl_cents < 0 else 0.5)

        # Running average of outcomes
        new_fitness = (current_fitness * current_count + outcome) / new_count
        self._fitness_cache[key] = (new_fitness, new_count)

        # Persist to SQLite
        try:
            with _db_connection(self.db_path, wal=True) as conn:
                conn.execute(
                    """INSERT INTO strategy_regime_fitness
                       (strategy_name, regime, fitness_score, trade_count,
                        total_pnl_cents, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(strategy_name, regime) DO UPDATE SET
                       fitness_score = excluded.fitness_score,
                       trade_count = excluded.trade_count,
                       total_pnl_cents = strategy_regime_fitness.total_pnl_cents + ?,
                       last_updated = excluded.last_updated""",
                    (
                        strategy_name, regime_val, new_fitness, new_count,
                        pnl_cents, datetime.now(timezone.utc).isoformat(),
                        pnl_cents,
                    ),
                )
        except Exception as e:
            logger.warning("Failed to persist fitness: %s", e)

    def get_recommended_strategies(
        self,
        regime: MarketRegime,
        confidence: float,
        active_strategies: List[str],
        safety_disabled: Optional[set] = None,
    ) -> Tuple[List[str], List[str]]:
        """
        Get strategies to enable/disable for the current regime.

        Returns:
            (to_enable, to_disable) — lists of strategy names.
        """
        safety_disabled = safety_disabled or set()
        to_enable = []
        to_disable = []

        for name in active_strategies:
            if name in safety_disabled:
                continue  # Never override safety layers

            fitness = self.get_fitness(name, regime)

            if fitness >= self.enable_threshold:
                to_enable.append(name)
            elif fitness < self.disable_threshold:
                to_disable.append(name)

        # Cap: never disable more than max_strategies_disabled_pct
        max_disables = int(len(active_strategies) * self.max_strategies_disabled_pct)
        if len(to_disable) > max_disables:
            # Keep the worst performers in to_disable, up to cap
            scored = [(name, self.get_fitness(name, regime)) for name in to_disable]
            scored.sort(key=lambda x: x[1])
            to_disable = [name for name, _ in scored[:max_disables]]

        return to_enable, to_disable


class BleedDetector:
    """
    Sliding-window P&L trend analysis to catch slow bleeds.

    Circuit breakers catch sharp losses (3 consecutive, drawdown).
    BleedDetector catches slow, steady drains that fly under the radar.
    """

    def __init__(
        self,
        window_hours: int = 24,
        threshold_cents: float = -50.0,
        slope_threshold: float = -0.5,
    ):
        self.window_hours = window_hours
        self.threshold_cents = threshold_cents
        self.slope_threshold = slope_threshold

        # Trade history: list of (timestamp, strategy_name, pnl_cents)
        self._trade_history: List[Tuple[datetime, str, float]] = []

    def record_trade(
        self, timestamp: datetime, strategy_name: str, pnl_cents: float
    ) -> None:
        """Record a closed trade for bleed analysis."""
        self._trade_history.append((timestamp, strategy_name, pnl_cents))
        # Trim to 2x window to keep memory bounded
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.window_hours * 2)
        self._trade_history = [
            t for t in self._trade_history if t[0] > cutoff
        ]

    def detect_portfolio_bleed(self) -> Optional[BleedSignal]:
        """Check for slow bleed at the portfolio level."""
        return self._detect_bleed(strategy_name=None)

    def detect_strategy_bleed(self, strategy_name: str) -> Optional[BleedSignal]:
        """Check for slow bleed in a specific strategy."""
        return self._detect_bleed(strategy_name=strategy_name)

    def _detect_bleed(self, strategy_name: Optional[str]) -> Optional[BleedSignal]:
        """Core bleed detection via linear regression of cumulative P&L."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.window_hours)

        # Filter trades in window
        trades = [
            t for t in self._trade_history
            if t[0] > cutoff and (strategy_name is None or t[1] == strategy_name)
        ]

        if len(trades) < 2:
            return None

        # Compute cumulative P&L and time series
        trades.sort(key=lambda t: t[0])
        start_time = trades[0][0]
        cumulative = 0.0
        xs = []  # hours from start
        ys = []  # cumulative P&L

        for ts, _, pnl in trades:
            hours = (ts - start_time).total_seconds() / 3600
            cumulative += pnl
            xs.append(hours)
            ys.append(cumulative)

        # Linear regression: slope = cents per hour
        slope = self._linear_slope(xs, ys)

        # Classify
        if cumulative < self.threshold_cents or slope < self.slope_threshold:
            classification = "slow_bleed"
        elif cumulative < self.threshold_cents * 3:
            classification = "sharp_loss"
        else:
            classification = "normal"

        if classification == "normal":
            return None

        return BleedSignal(
            strategy_name=strategy_name,
            classification=classification,
            cumulative_pnl_cents=cumulative,
            slope_cents_per_hour=slope,
            window_hours=self.window_hours,
        )

    @staticmethod
    def _linear_slope(xs: List[float], ys: List[float]) -> float:
        """Simple linear regression slope."""
        n = len(xs)
        if n < 2:
            return 0.0

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator = sum((x - mean_x) ** 2 for x in xs)

        if denominator == 0:
            return 0.0

        return numerator / denominator


class CycleAnalyzer:
    """
    Predicts tomorrow's market regime from historical patterns and external signals.

    Uses 4 weighted factors:
    1. Day-of-week regime distribution (weight: 0.2) — needs 7+ days of data
    2. Recent momentum (weight: 0.3) — last few regime snapshots
    3. External signals (weight: 0.3) — S&P 500 change and VIX via yfinance
    4. Calendar events (weight: 0.2) — FOMC + CPI dates for 2026

    Gracefully degrades without yfinance (redistributes weight to other factors).
    """

    WEIGHTS = {
        "day_of_week": 0.2,
        "momentum": 0.3,
        "external": 0.3,
        "calendar": 0.2,
    }

    # FOMC meeting dates 2026 (Fed funds rate decisions).
    # WARNING: Update annually. After 2026, _calendar_signal() returns None silently.
    FOMC_DATES_2026 = {
        (1, 28), (1, 29),   # Jan 28-29
        (3, 17), (3, 18),   # Mar 17-18
        (5, 5), (5, 6),     # May 5-6
        (6, 16), (6, 17),   # Jun 16-17
        (7, 28), (7, 29),   # Jul 28-29
        (9, 15), (9, 16),   # Sep 15-16
        (10, 27), (10, 28), # Oct 27-28
        (12, 15), (12, 16), # Dec 15-16
    }

    # CPI release dates 2026 (approximate: ~10th-15th of each month).
    # WARNING: Update annually alongside FOMC dates.
    CPI_DATES_2026 = {
        (1, 14), (2, 12), (3, 11), (4, 14), (5, 13), (6, 10),
        (7, 14), (8, 12), (9, 10), (10, 13), (11, 12), (12, 10),
    }

    def __init__(self, db_path: str):
        self.db_path = Path(db_path).expanduser()
        self._external_cache: Optional[Dict[str, float]] = None
        self._external_cache_time: Optional[datetime] = None
        self._external_cache_ttl = timedelta(hours=4)

    def predict(
        self, current_regime: Optional[RegimeSnapshot] = None
    ) -> RegimePrediction:
        """Predict the next regime using available signals."""
        votes: Dict[MarketRegime, float] = {r: 0.0 for r in MarketRegime}
        used_weights = 0.0
        factors = {}

        # 1. Day-of-week pattern
        dow_prediction = self._day_of_week_signal()
        if dow_prediction:
            for regime, weight in dow_prediction.items():
                votes[regime] += weight * self.WEIGHTS["day_of_week"]
            used_weights += self.WEIGHTS["day_of_week"]
            factors["day_of_week"] = {r.value: w for r, w in dow_prediction.items()}

        # 2. Recent momentum
        if current_regime:
            momentum_regime = current_regime.regime
            votes[momentum_regime] += self.WEIGHTS["momentum"]
            used_weights += self.WEIGHTS["momentum"]
            factors["momentum"] = momentum_regime.value

        # 3. External signals
        external = self._get_external_signals()
        if external:
            ext_regime = self._external_to_regime(external)
            votes[ext_regime] += self.WEIGHTS["external"]
            used_weights += self.WEIGHTS["external"]
            factors["external"] = external

        # 4. Calendar events
        cal_regime = self._calendar_signal()
        if cal_regime:
            votes[cal_regime] += self.WEIGHTS["calendar"]
            used_weights += self.WEIGHTS["calendar"]
            factors["calendar"] = cal_regime.value

        # Normalize votes
        if used_weights > 0:
            for r in votes:
                votes[r] /= used_weights

        # Pick winner
        best_regime = max(votes, key=lambda r: votes[r])
        confidence = votes[best_regime]

        # Discount confidence if we're missing signals
        confidence *= min(used_weights / sum(self.WEIGHTS.values()), 1.0)

        return RegimePrediction(
            predicted_regime=best_regime,
            confidence=round(confidence, 3),
            factors=factors,
        )

    def _day_of_week_signal(self) -> Optional[Dict[MarketRegime, float]]:
        """Query regime_history for day-of-week patterns."""
        try:
            with _db_connection(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT regime, timestamp FROM regime_history "
                    "ORDER BY timestamp DESC LIMIT 500"
                ).fetchall()
        except Exception:
            return None

        if len(rows) < 7:
            return None

        # Count regimes by day of week for tomorrow
        tomorrow_dow = (datetime.now(timezone.utc) + timedelta(days=1)).weekday()
        dow_counts: Dict[MarketRegime, int] = {r: 0 for r in MarketRegime}
        total = 0

        for regime_val, ts_str in rows:
            try:
                # Handle both ISO format and SQLite default format (space separator)
                if " " in ts_str and "T" not in ts_str:
                    ts_str = ts_str.replace(" ", "T")
                ts = datetime.fromisoformat(ts_str)
                if ts.weekday() == tomorrow_dow:
                    regime = MarketRegime(regime_val)
                    dow_counts[regime] += 1
                    total += 1
            except ValueError:
                continue

        if total == 0:
            return None

        return {r: count / total for r, count in dow_counts.items()}

    def _get_external_signals(self) -> Optional[Dict[str, float]]:
        """Get S&P 500 change and VIX from yfinance with 4h cache."""
        now = datetime.now(timezone.utc)

        # Check cache
        if (
            self._external_cache is not None
            and self._external_cache_time is not None
            and (now - self._external_cache_time) < self._external_cache_ttl
        ):
            return self._external_cache

        try:
            import yfinance as yf

            spy = yf.Ticker("SPY")
            hist = spy.history(period="2d")
            if len(hist) < 2:
                return None

            sp500_change = (hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2]

            vix = yf.Ticker("^VIX")
            vix_hist = vix.history(period="1d")
            vix_level = float(vix_hist["Close"].iloc[-1]) if len(vix_hist) > 0 else 20.0

            self._external_cache = {
                "sp500_change_pct": round(float(sp500_change) * 100, 3),
                "vix_level": round(vix_level, 2),
            }
            self._external_cache_time = now
            return self._external_cache

        except Exception as e:
            logger.debug("External data unavailable: %s", e)
            return None

    def _external_to_regime(self, external: Dict[str, float]) -> MarketRegime:
        """Map external signals to a likely regime."""
        sp_change = external.get("sp500_change_pct", 0)
        vix = external.get("vix_level", 20)

        if vix > 30:
            return MarketRegime.HIGH_VOL_CHOPPY
        if sp_change > 0.5:
            return MarketRegime.TRENDING_UP
        if sp_change < -0.5:
            return MarketRegime.TRENDING_DOWN
        if vix < 15:
            return MarketRegime.LOW_VOL_CALM
        return MarketRegime.MEAN_REVERTING

    def _calendar_signal(self) -> Optional[MarketRegime]:
        """Check if tomorrow is near an FOMC/CPI date."""
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        month_day = (tomorrow.month, tomorrow.day)

        # Check +/- 1 day around events
        for delta in (-1, 0, 1):
            check = tomorrow + timedelta(days=delta)
            check_md = (check.month, check.day)
            if check_md in self.FOMC_DATES_2026 or check_md in self.CPI_DATES_2026:
                return MarketRegime.HIGH_VOL_CHOPPY

        return None


class GovernanceEngine:
    """
    Orchestrator that coordinates regime detection and strategy routing.

    Hooks into the trading cycle between AI analysis and market scanning.
    Respects all existing safety layers — never overrides circuit breakers,
    daily limits, or emotional firewall.

    Phase 1: Regime detection + logging
    Phase 2: Strategy routing + bleed detection (StrategyRouter, BleedDetector)
    Phase 3: Cycle analysis + prediction (CycleAnalyzer)
    """

    def __init__(
        self,
        db_path: str,
        enabled: bool = False,
        mode: str = "advisory",
        lookback_periods: int = 20,
        min_confidence: float = 0.6,
        fitness_min_trades: int = 5,
        enable_threshold: float = 0.5,
        disable_threshold: float = 0.3,
        bleed_window_hours: int = 24,
        bleed_threshold_cents: float = -50.0,
        bleed_slope_threshold: float = -0.5,
        max_strategies_disabled_pct: float = 0.75,
        reenable_cooldown_hours: int = 6,
    ):
        self.db_path = Path(db_path).expanduser()
        self.enabled = enabled
        self.mode = mode
        self.min_confidence = min_confidence
        self.fitness_min_trades = fitness_min_trades
        self.enable_threshold = enable_threshold
        self.disable_threshold = disable_threshold
        self.bleed_window_hours = bleed_window_hours
        self.bleed_threshold_cents = bleed_threshold_cents
        self.bleed_slope_threshold = bleed_slope_threshold
        self.max_strategies_disabled_pct = max_strategies_disabled_pct
        self.reenable_cooldown_hours = reenable_cooldown_hours

        self.regime_detector = RegimeDetector(lookback_periods=lookback_periods)
        self.strategy_router = StrategyRouter(
            db_path=str(self.db_path),
            prior_strength=fitness_min_trades,
            enable_threshold=enable_threshold,
            disable_threshold=disable_threshold,
            max_strategies_disabled_pct=max_strategies_disabled_pct,
        )
        self.bleed_detector = BleedDetector(
            window_hours=bleed_window_hours,
            threshold_cents=bleed_threshold_cents,
            slope_threshold=bleed_slope_threshold,
        )
        self.cycle_analyzer = CycleAnalyzer(db_path=str(self.db_path))
        self.current_regime: Optional[RegimeSnapshot] = None
        self.current_prediction: Optional[RegimePrediction] = None
        self._decisions: List[GovernanceDecision] = []

        # Track governance-disabled strategies and their cooldown times
        self._governance_disabled: Dict[str, datetime] = {}

        logger.info(
            "GovernanceEngine initialized | enabled=%s, mode=%s, lookback=%d",
            enabled, mode, lookback_periods,
        )

    def feed_market_data(self, markets: List[MarketSnapshot]) -> None:
        """Feed a batch of market data from the current trading cycle."""
        self.regime_detector.add_snapshot(markets)

    async def run_cycle(
        self,
        active_strategies: Optional[List[str]] = None,
        safety_disabled: Optional[set] = None,
        strategy_manager: Any = None,
    ) -> Optional[RegimeSnapshot]:
        """
        Run one governance cycle: detect regime, route strategies, check bleeds.

        Args:
            active_strategies: List of currently registered strategy names.
            safety_disabled: Set of strategies disabled by safety layers (never touch).
            strategy_manager: StrategyManager instance for autonomous mode actions.

        Returns:
            Current RegimeSnapshot, or None if governance is disabled.
        """
        if not self.enabled:
            return None

        active_strategies = active_strategies or []
        safety_disabled = safety_disabled or set()

        snapshot = self.regime_detector.detect()
        self.current_regime = snapshot

        # Persist regime
        self._persist_regime(snapshot)

        logger.info(
            "Governance | regime=%s confidence=%.2f volatility=%.2f "
            "trend=%.2f mean_rev=%.2f vol_ratio=%.2f markets=%d",
            snapshot.regime.value,
            snapshot.confidence,
            snapshot.volatility,
            snapshot.trend_strength,
            snapshot.mean_reversion_score,
            snapshot.volume_ratio,
            snapshot.num_markets_sampled,
        )

        # Strategy routing (only if confidence meets threshold)
        if snapshot.confidence >= self.min_confidence and active_strategies:
            to_enable, to_disable = self.strategy_router.get_recommended_strategies(
                regime=snapshot.regime,
                confidence=snapshot.confidence,
                active_strategies=active_strategies,
                safety_disabled=safety_disabled,
            )

            for name in to_disable:
                self._record_routing_decision(
                    snapshot, name, action_type="disable",
                    threshold=self.disable_threshold, direction="below",
                )
                if self.mode == "autonomous" and strategy_manager:
                    self._governance_disabled[name] = snapshot.timestamp
                    strategy_manager.disable_strategy(name)
                    logger.info("Governance DISABLED strategy '%s' (regime=%s)", name, snapshot.regime.value)

            for name in to_enable:
                # Check cooldown before re-enabling
                if name in self._governance_disabled:
                    disabled_at = self._governance_disabled[name]
                    hours_since = (snapshot.timestamp - disabled_at).total_seconds() / 3600
                    if hours_since < self.reenable_cooldown_hours:
                        continue
                    del self._governance_disabled[name]

                self._record_routing_decision(
                    snapshot, name, action_type="enable",
                    threshold=self.enable_threshold, direction="above",
                )
                if self.mode == "autonomous" and strategy_manager:
                    strategy_manager.enable_strategy(name)
                    logger.info("Governance ENABLED strategy '%s' (regime=%s)", name, snapshot.regime.value)

        # Bleed detection
        bleed = self.bleed_detector.detect_portfolio_bleed()
        if bleed:
            self._record_decision(GovernanceDecision(
                timestamp=snapshot.timestamp,
                regime=snapshot.regime,
                regime_confidence=snapshot.confidence,
                action="bleed_alert",
                strategy_name=None,
                reason=(
                    f"Portfolio {bleed.classification}: cumulative={bleed.cumulative_pnl_cents:.1f}c "
                    f"slope={bleed.slope_cents_per_hour:.2f}c/hr over {bleed.window_hours}h"
                ),
                mode=self.mode,
            ))
            logger.warning(
                "Governance BLEED ALERT | %s | pnl=%.1fc slope=%.2fc/hr",
                bleed.classification,
                bleed.cumulative_pnl_cents,
                bleed.slope_cents_per_hour,
            )

        # Cycle prediction (Phase 3)
        prediction = self.cycle_analyzer.predict(current_regime=snapshot)
        self.current_prediction = prediction
        if prediction.confidence > 0.3:
            logger.info(
                "Governance PREDICTION | next=%s confidence=%.2f factors=%s",
                prediction.predicted_regime.value,
                prediction.confidence,
                list(prediction.factors.keys()),
            )

        return snapshot

    def record_trade_outcome(
        self, strategy_name: str, pnl_cents: float
    ) -> None:
        """Record a closed trade for both fitness attribution and bleed detection."""
        now = datetime.now(timezone.utc)

        # Update bleed detector
        self.bleed_detector.record_trade(now, strategy_name, pnl_cents)

        # Update fitness for current regime
        if self.current_regime:
            self.strategy_router.record_trade_outcome(
                strategy_name, self.current_regime.regime, pnl_cents
            )

    def _record_decision(self, decision: GovernanceDecision) -> None:
        """Persist a governance decision and keep it in memory."""
        self._persist_decision(decision)
        self._decisions.append(decision)

    def _record_routing_decision(
        self,
        snapshot: RegimeSnapshot,
        strategy_name: str,
        action_type: str,
        threshold: float,
        direction: str,
    ) -> None:
        """Build and record a strategy routing decision (enable or disable)."""
        is_autonomous = self.mode == "autonomous"
        action = action_type if is_autonomous else f"advisory_{action_type}"
        fitness = self.strategy_router.get_fitness(strategy_name, snapshot.regime)

        self._record_decision(GovernanceDecision(
            timestamp=snapshot.timestamp,
            regime=snapshot.regime,
            regime_confidence=snapshot.confidence,
            action=action,
            strategy_name=strategy_name,
            reason=f"Fitness {fitness:.2f} {direction} threshold {threshold} in {snapshot.regime.value}",
            mode=self.mode,
        ))

    def _persist_regime(self, snapshot: RegimeSnapshot) -> None:
        """Save regime snapshot to SQLite."""
        try:
            with _db_connection(self.db_path, wal=True) as conn:
                conn.execute(
                    """INSERT INTO regime_history
                       (regime, confidence, timestamp, volatility, trend_strength,
                        mean_reversion_score, volume_ratio, num_markets_sampled)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot.regime.value,
                        snapshot.confidence,
                        snapshot.timestamp.isoformat(),
                        snapshot.volatility,
                        snapshot.trend_strength,
                        snapshot.mean_reversion_score,
                        snapshot.volume_ratio,
                        snapshot.num_markets_sampled,
                    ),
                )
        except Exception as e:
            logger.warning("Failed to persist regime: %s", e)

    def _persist_decision(self, decision: GovernanceDecision) -> None:
        """Save governance decision to SQLite for audit trail."""
        try:
            with _db_connection(self.db_path, wal=True) as conn:
                conn.execute(
                    """INSERT INTO governance_decisions
                       (timestamp, regime, regime_confidence, action,
                        strategy_name, reason, mode)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        decision.timestamp.isoformat(),
                        decision.regime.value,
                        decision.regime_confidence,
                        decision.action,
                        decision.strategy_name,
                        decision.reason,
                        decision.mode,
                    ),
                )
        except Exception as e:
            logger.warning("Failed to persist governance decision: %s", e)

    def get_recent_decisions(self, limit: int = 10) -> List[GovernanceDecision]:
        """Return the most recent governance decisions from memory."""
        return self._decisions[-limit:]
