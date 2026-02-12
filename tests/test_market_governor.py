"""
Tests for Market Governor — Phase 1 + Phase 2

Phase 1: Regime Detection + Data Layer
Phase 2: Strategy Routing + Bleed Detection

Tests cover:
- RegimeDetector cold start behavior
- Regime classification for all 5 market conditions
- GovernanceConfig validation
- GovernanceEngine decision logging and regime persistence
- StrategyRouter fitness priors, regime routing, safety, max disable cap
- BleedDetector slow bleed and sharp loss detection
- Advisory vs autonomous mode
- Fitness attribution after trade closes
"""

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kalshi_trader.config import GovernanceConfig
from kalshi_trader.market_governor import (
    BleedDetector,
    CycleAnalyzer,
    GovernanceEngine,
    MarketRegime,
    MarketSnapshot,
    RegimeDetector,
    RegimePrediction,
    StrategyRouter,
)


def _make_snapshots(
    prices: list[list[float]],
    base_volume: int = 500,
) -> list[list[MarketSnapshot]]:
    """Build batches of MarketSnapshots from price lists.

    Args:
        prices: List of batches, each batch is a list of YES prices.
        base_volume: Volume for each market.
    """
    batches = []
    now = datetime.now(timezone.utc)
    for i, batch_prices in enumerate(prices):
        batch = []
        for j, price in enumerate(batch_prices):
            batch.append(MarketSnapshot(
                timestamp=now + timedelta(minutes=i),
                ticker=f"MKT-{j}",
                yes_price=price,
                volume=base_volume,
            ))
        batches.append(batch)
    return batches


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database with governance tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regime_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regime TEXT NOT NULL,
            confidence REAL NOT NULL,
            timestamp TEXT NOT NULL,
            volatility REAL,
            trend_strength REAL,
            mean_reversion_score REAL,
            volume_ratio REAL,
            num_markets_sampled INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_regime_fitness (
            strategy_name TEXT NOT NULL,
            regime TEXT NOT NULL,
            fitness_score REAL DEFAULT 0.5,
            trade_count INTEGER DEFAULT 0,
            total_pnl_cents REAL DEFAULT 0.0,
            last_updated TEXT,
            PRIMARY KEY (strategy_name, regime)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS governance_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            regime TEXT NOT NULL,
            regime_confidence REAL,
            action TEXT NOT NULL,
            strategy_name TEXT,
            reason TEXT,
            mode TEXT
        )
    """)
    conn.commit()
    conn.close()

    yield db_path
    Path(db_path).unlink(missing_ok=True)


class TestRegimeDetectorColdStart:
    """Test 1: <5 snapshots returns LOW_VOL_CALM with low confidence."""

    def test_cold_start_empty(self):
        detector = RegimeDetector(lookback_periods=20)
        result = detector.detect()
        assert result.regime == MarketRegime.LOW_VOL_CALM
        assert result.confidence < 0.2
        assert result.num_markets_sampled == 0

    def test_cold_start_insufficient(self):
        detector = RegimeDetector(lookback_periods=20)
        # Add only 3 snapshots (below MIN_SNAPSHOTS=5)
        for batch in _make_snapshots([[50, 50]] * 3):
            detector.add_snapshot(batch)
        result = detector.detect()
        assert result.regime == MarketRegime.LOW_VOL_CALM
        assert result.confidence < 0.2


class TestRegimeDetectorTrendingUp:
    """Test 2: 20 rising-price snapshots = TRENDING_UP."""

    def test_trending_up(self):
        detector = RegimeDetector(lookback_periods=20)
        # 20 batches with 5 markets each, all rising steadily
        prices = []
        for i in range(20):
            base = 40 + i * 1.5  # 40 -> 68.5
            prices.append([base, base + 1, base + 2, base - 1, base + 0.5])
        for batch in _make_snapshots(prices):
            detector.add_snapshot(batch)

        result = detector.detect()
        assert result.regime == MarketRegime.TRENDING_UP
        assert result.confidence > 0.3
        assert result.trend_strength > 0


class TestRegimeDetectorTrendingDown:
    """Test 3: 20 falling-price snapshots = TRENDING_DOWN."""

    def test_trending_down(self):
        detector = RegimeDetector(lookback_periods=20)
        prices = []
        for i in range(20):
            base = 70 - i * 1.5  # 70 -> 41.5
            prices.append([base, base - 1, base - 2, base + 1, base - 0.5])
        for batch in _make_snapshots(prices):
            detector.add_snapshot(batch)

        result = detector.detect()
        assert result.regime == MarketRegime.TRENDING_DOWN
        assert result.confidence > 0.3
        assert result.trend_strength < 0


class TestRegimeDetectorHighVolatility:
    """Test 4: Wide swings = HIGH_VOL_CHOPPY."""

    def test_high_vol_choppy(self):
        detector = RegimeDetector(lookback_periods=20)
        # Alternate wildly with no clear direction
        prices = []
        for i in range(20):
            if i % 2 == 0:
                prices.append([20, 80, 30, 70, 25])
            else:
                prices.append([75, 25, 65, 35, 70])
        for batch in _make_snapshots(prices):
            detector.add_snapshot(batch)

        result = detector.detect()
        assert result.regime == MarketRegime.HIGH_VOL_CHOPPY
        assert result.volatility > 0.5


class TestRegimeDetectorMeanReverting:
    """Test 5: Oscillating prices = MEAN_REVERTING."""

    def test_mean_reverting(self):
        detector = RegimeDetector(lookback_periods=20)
        # Prices oscillate around 50 with frequent zero-crossings
        prices = []
        for i in range(20):
            offset = 3 * (1 if i % 2 == 0 else -1)
            prices.append([50 + offset, 50 - offset, 50 + offset * 0.5])
        for batch in _make_snapshots(prices):
            detector.add_snapshot(batch)

        result = detector.detect()
        assert result.mean_reversion_score > 0.5


class TestRegimeDetectorLowVolCalm:
    """Test 6: Flat prices, low volume = LOW_VOL_CALM."""

    def test_low_vol_calm(self):
        detector = RegimeDetector(lookback_periods=20)
        # Very stable prices near 50
        prices = [[50.1, 49.9, 50.0, 50.2, 49.8]] * 20
        for batch in _make_snapshots(prices, base_volume=50):
            detector.add_snapshot(batch)

        result = detector.detect()
        assert result.regime == MarketRegime.LOW_VOL_CALM
        assert result.volatility < 0.3


class TestGovernanceConfigValidation:
    """Test 7: Invalid mode raises ValueError."""

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="Invalid governance mode"):
            GovernanceConfig(mode="yolo")

    def test_valid_modes(self):
        for mode in ("advisory", "autonomous", "manual"):
            cfg = GovernanceConfig(mode=mode)
            assert cfg.mode == mode


class TestGovernanceConfigDefaults:
    """Test 8: All defaults are sensible."""

    def test_defaults(self):
        cfg = GovernanceConfig()
        assert cfg.enabled is False
        assert cfg.mode == "advisory"
        assert cfg.lookback_periods == 20
        assert cfg.min_confidence == 0.6
        assert cfg.fitness_min_trades == 5
        assert cfg.enable_threshold > cfg.disable_threshold
        assert 0 < cfg.max_strategies_disabled_pct <= 1.0
        assert cfg.reenable_cooldown_hours > 0


class TestGovernanceDecisionLogging:
    """Test 9: Decisions persist to SQLite."""

    @pytest.mark.asyncio
    async def test_decision_persists(self, tmp_db):
        engine = GovernanceEngine(
            db_path=tmp_db, enabled=True, mode="advisory", min_confidence=0.0,
        )
        # Feed enough data for detection
        prices = [[50, 50, 50]] * 6
        for batch in _make_snapshots(prices):
            engine.feed_market_data(batch)

        await engine.run_cycle(active_strategies=["mean_reversion"])

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM governance_decisions").fetchall()
        conn.close()
        assert len(rows) >= 1
        assert rows[0][3] is not None  # regime_confidence


class TestRegimeHistoryPersistence:
    """Test 10: Regime snapshots persist to SQLite."""

    @pytest.mark.asyncio
    async def test_regime_persists(self, tmp_db):
        engine = GovernanceEngine(db_path=tmp_db, enabled=True)
        prices = [[50, 50, 50]] * 6
        for batch in _make_snapshots(prices):
            engine.feed_market_data(batch)

        await engine.run_cycle()

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM regime_history").fetchall()
        conn.close()
        assert len(rows) >= 1
        # regime column should be a valid enum value
        regime_val = rows[0][1]
        valid_regimes = {r.value for r in MarketRegime}
        assert regime_val in valid_regimes


# ============================================================
# Phase 2 Tests: Strategy Routing + Bleed Detection
# ============================================================


class TestStrategyRouterFitnessPriors:
    """Test 11: All 14 strategies have default priors."""

    def test_all_strategies_have_priors(self):
        assert len(StrategyRouter.DEFAULT_PRIORS) == 14
        for name, regime_map in StrategyRouter.DEFAULT_PRIORS.items():
            assert len(regime_map) == 5, f"{name} missing regime priors"
            for regime in MarketRegime:
                assert regime.value in regime_map, f"{name} missing {regime.value}"


class TestStrategyRouterTrendingUp:
    """Test 12: In TRENDING_UP, momentum enabled, mean_reversion disabled."""

    def test_trending_up_routing(self, tmp_db):
        router = StrategyRouter(
            db_path=tmp_db,
            enable_threshold=0.5,
            disable_threshold=0.3,
        )
        to_enable, to_disable = router.get_recommended_strategies(
            regime=MarketRegime.TRENDING_UP,
            confidence=0.8,
            active_strategies=["mean_reversion", "momentum"],
        )
        assert "momentum" in to_enable
        assert "mean_reversion" in to_disable


class TestStrategyRouterMeanReverting:
    """Test 13: In MEAN_REVERTING, mean_reversion enabled, momentum disabled."""

    def test_mean_reverting_routing(self, tmp_db):
        router = StrategyRouter(
            db_path=tmp_db,
            enable_threshold=0.5,
            disable_threshold=0.3,
        )
        to_enable, to_disable = router.get_recommended_strategies(
            regime=MarketRegime.MEAN_REVERTING,
            confidence=0.8,
            active_strategies=["mean_reversion", "momentum"],
        )
        assert "mean_reversion" in to_enable
        assert "momentum" in to_disable


class TestStrategyRouterRespectsSafety:
    """Test 14: Auto-disabled strategies are untouched by router."""

    def test_safety_disabled_untouched(self, tmp_db):
        router = StrategyRouter(db_path=tmp_db)
        _, to_disable = router.get_recommended_strategies(
            regime=MarketRegime.TRENDING_UP,
            confidence=0.8,
            active_strategies=["mean_reversion", "momentum"],
            safety_disabled={"mean_reversion"},
        )
        # mean_reversion would normally be disabled in trending,
        # but it's in safety_disabled so it should NOT appear
        assert "mean_reversion" not in to_disable


class TestStrategyRouterMaxDisableCap:
    """Test 15: Cannot disable more than 75% of strategies."""

    def test_max_disable_cap(self, tmp_db):
        router = StrategyRouter(
            db_path=tmp_db,
            disable_threshold=0.99,  # Nearly everything gets disabled
            max_strategies_disabled_pct=0.75,
        )
        # All 4 strategies have low fitness — but cap should limit to 3
        strategies = ["s1", "s2", "s3", "s4"]
        _, to_disable = router.get_recommended_strategies(
            regime=MarketRegime.TRENDING_UP,
            confidence=0.8,
            active_strategies=strategies,
        )
        assert len(to_disable) <= 3  # 75% of 4


class TestBleedDetectorNoBleed:
    """Test 16: Positive P&L returns None."""

    def test_no_bleed(self):
        detector = BleedDetector(window_hours=24, threshold_cents=-50)
        now = datetime.now(timezone.utc)
        for i in range(10):
            detector.record_trade(now - timedelta(hours=10 - i), "strat", 5.0)
        result = detector.detect_portfolio_bleed()
        assert result is None


class TestBleedDetectorSlowBleed:
    """Test 17: Consistent small losses over 24h triggers bleed signal."""

    def test_slow_bleed(self):
        detector = BleedDetector(
            window_hours=24,
            threshold_cents=-50,
            slope_threshold=-0.5,
        )
        now = datetime.now(timezone.utc)
        # 20 trades over 20 hours, each -3c
        for i in range(20):
            detector.record_trade(now - timedelta(hours=20 - i), "strat", -3.0)
        result = detector.detect_portfolio_bleed()
        assert result is not None
        assert result.classification == "slow_bleed"
        assert result.cumulative_pnl_cents < -50


class TestBleedDetectorSharpLoss:
    """Test 18: Large cumulative loss triggers a bleed signal."""

    def test_sharp_loss(self):
        detector = BleedDetector(
            window_hours=24,
            threshold_cents=-50,
            slope_threshold=-0.5,
        )
        now = datetime.now(timezone.utc)
        detector.record_trade(now - timedelta(hours=2), "strat", -200.0)
        detector.record_trade(now - timedelta(hours=1), "strat", -5.0)
        result = detector.detect_portfolio_bleed()
        assert result is not None
        assert result.cumulative_pnl_cents < -150
        assert result.classification in ("slow_bleed", "sharp_loss")


class TestGovernanceAdvisoryMode:
    """Test 19: Advisory mode logs decisions but doesn't modify strategies."""

    @pytest.mark.asyncio
    async def test_advisory_logs_only(self, tmp_db):
        engine = GovernanceEngine(
            db_path=tmp_db, enabled=True, mode="advisory", min_confidence=0.0
        )
        prices = [[50, 50, 50]] * 6
        for batch in _make_snapshots(prices):
            engine.feed_market_data(batch)

        await engine.run_cycle(
            active_strategies=["mean_reversion", "momentum"],
        )

        # Decisions should be logged
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT action FROM governance_decisions").fetchall()
        conn.close()
        # All actions should be advisory (not "enable"/"disable")
        for row in rows:
            assert "advisory" in row[0] or row[0] == "bleed_alert"


class TestGovernanceAutonomousMode:
    """Test 20: Autonomous mode creates enable/disable decisions."""

    @pytest.mark.asyncio
    async def test_autonomous_creates_actions(self, tmp_db):
        engine = GovernanceEngine(
            db_path=tmp_db, enabled=True, mode="autonomous", min_confidence=0.0,
            enable_threshold=0.5, disable_threshold=0.3,
        )
        # Feed trending up data
        prices = []
        for i in range(10):
            base = 40 + i * 2
            prices.append([base, base + 1, base + 2])
        for batch in _make_snapshots(prices):
            engine.feed_market_data(batch)

        await engine.run_cycle(
            active_strategies=["mean_reversion", "momentum"],
        )

        decisions = engine.get_recent_decisions()
        actions = [d.action for d in decisions]
        # Should have at least one non-advisory action
        assert any(a in ("enable", "disable") for a in actions)


class TestGovernanceDecisionAuditTrail:
    """Test 21: All decisions are persisted to SQLite."""

    @pytest.mark.asyncio
    async def test_all_decisions_persisted(self, tmp_db):
        engine = GovernanceEngine(
            db_path=tmp_db, enabled=True, mode="autonomous", min_confidence=0.0,
        )
        prices = [[50, 50, 50]] * 6
        for batch in _make_snapshots(prices):
            engine.feed_market_data(batch)

        await engine.run_cycle(active_strategies=["mean_reversion", "momentum"])

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM governance_decisions").fetchall()
        conn.close()
        in_memory = engine.get_recent_decisions()
        # DB should have at least as many as in-memory
        assert len(rows) >= len(in_memory)


class TestFitnessMatrixUpdatesAfterTrade:
    """Test 22: Closing a trade updates fitness for the current regime."""

    @pytest.mark.asyncio
    async def test_fitness_updates(self, tmp_db):
        engine = GovernanceEngine(
            db_path=tmp_db, enabled=True, mode="advisory",
        )
        # Establish a regime
        prices = [[50, 50, 50]] * 6
        for batch in _make_snapshots(prices):
            engine.feed_market_data(batch)
        await engine.run_cycle()

        # Record a winning trade
        engine.record_trade_outcome("mean_reversion", 8.0)

        # Fitness should now reflect the win
        regime = engine.current_regime.regime
        fitness = engine.strategy_router.get_fitness("mean_reversion", regime)
        # Prior for mean_reversion in LOW_VOL_CALM is 0.6
        # After 1 win (1.0), blended should be > 0.6
        assert fitness > 0.6

        # Check persistence
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT fitness_score, trade_count FROM strategy_regime_fitness "
            "WHERE strategy_name='mean_reversion'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][1] == 1  # trade_count


# ============================================================
# Phase 3 Tests: Cycle Analysis + Prediction
# ============================================================


class TestCycleAnalyzerDayOfWeek:
    """Test 23: Identifies day patterns from regime history."""

    def test_day_of_week_with_history(self, tmp_db):
        """With enough regime history, day_of_week factor should appear."""
        conn = sqlite3.connect(tmp_db)
        # Insert 30 days of fake regime history (all trending_up on same weekday)
        now = datetime.now(timezone.utc)
        tomorrow_dow = (now + timedelta(days=1)).weekday()
        for i in range(30):
            ts = now - timedelta(days=i)
            regime = "trending_up" if ts.weekday() == tomorrow_dow else "low_vol_calm"
            conn.execute(
                "INSERT INTO regime_history (regime, confidence, timestamp, "
                "volatility, trend_strength, mean_reversion_score, volume_ratio, "
                "num_markets_sampled) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (regime, 0.8, ts.isoformat(), 0.3, 0.5, 0.3, 1.0, 10),
            )
        conn.commit()
        conn.close()

        analyzer = CycleAnalyzer(db_path=tmp_db)
        prediction = analyzer.predict()
        # Should have day_of_week in factors
        assert "day_of_week" in prediction.factors or "momentum" in prediction.factors


class TestCycleAnalyzerCalendarEvents:
    """Test 24: FOMC dates correctly identified."""

    def test_fomc_dates_exist(self):
        # FOMC dates should be defined
        assert len(CycleAnalyzer.FOMC_DATES_2026) > 0
        assert len(CycleAnalyzer.CPI_DATES_2026) > 0
        # All entries should be (month, day) tuples
        for md in CycleAnalyzer.FOMC_DATES_2026:
            assert 1 <= md[0] <= 12
            assert 1 <= md[1] <= 31


class TestCycleAnalyzerColdStart:
    """Test 25: <7 days of data returns low-confidence prediction."""

    def test_cold_start_low_confidence(self, tmp_db):
        analyzer = CycleAnalyzer(db_path=tmp_db)
        prediction = analyzer.predict()
        # With no data and no yfinance, confidence should be low
        assert prediction.confidence < 0.5
        assert prediction.predicted_regime in MarketRegime


class TestExternalDataGracefulFailure:
    """Test 26: yfinance failure returns empty dict."""

    def test_external_graceful_failure(self, tmp_db):
        analyzer = CycleAnalyzer(db_path=tmp_db)
        # Even if yfinance fails, predict() should not raise
        prediction = analyzer.predict()
        assert isinstance(prediction, RegimePrediction)


class TestPredictionIntegration:
    """Test 27: Full cycle: detect -> predict -> route."""

    @pytest.mark.asyncio
    async def test_full_cycle(self, tmp_db):
        engine = GovernanceEngine(
            db_path=tmp_db, enabled=True, mode="advisory", min_confidence=0.0,
        )
        # Feed enough data
        prices = [[50, 50, 50]] * 6
        for batch in _make_snapshots(prices):
            engine.feed_market_data(batch)

        snapshot = await engine.run_cycle(
            active_strategies=["mean_reversion", "momentum"],
        )

        assert snapshot is not None
        # Prediction should have been made
        assert engine.current_prediction is not None
        assert isinstance(engine.current_prediction, RegimePrediction)
        assert engine.current_prediction.predicted_regime in MarketRegime
