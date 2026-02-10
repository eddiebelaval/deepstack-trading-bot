"""Tests for CorrelatedEventArbitrageStrategy"""

import pytest
from strategies.correlated_event_arbitrage import (
    CorrelatedEventArbitrageStrategy,
    ImplicationDetector,
)


@pytest.fixture
def strategy():
    return CorrelatedEventArbitrageStrategy({})


@pytest.fixture
def detector():
    return ImplicationDetector()


class TestImplicationDetector:
    def test_party_candidate_implication(self, detector, implication_markets):
        rels = detector.detect_relationships(implication_markets)
        assert len(rels) >= 1
        rel = rels[0]
        assert rel.relationship_type == "implication"
        assert "trump" in rel.antecedent_title.lower() or "republican" in rel.consequent_title.lower()

    def test_threshold_subset(self, detector):
        markets = [
            {
                "ticker": "SP-5000",
                "title": "Will S&P 500 be above 5000?",
                "status": "open",
                "yes_bid": 60,
                "yes_ask": 64,
                "volume": 1000,
            },
            {
                "ticker": "SP-4500",
                "title": "Will S&P 500 be above 4500?",
                "status": "open",
                "yes_bid": 55,
                "yes_ask": 59,
                "volume": 1000,
            },
        ]
        rels = detector.detect_relationships(markets)
        assert len(rels) >= 1
        rel = rels[0]
        assert rel.relationship_type == "subset"
        # Higher threshold is antecedent (implies lower threshold)
        assert "5000" in rel.antecedent_title

    def test_no_relationship(self, detector):
        markets = [
            {
                "ticker": "A",
                "title": "Will it rain in NYC?",
                "status": "open",
                "yes_bid": 50,
                "yes_ask": 54,
                "volume": 1000,
            },
            {
                "ticker": "B",
                "title": "Will Bitcoin reach $200K?",
                "status": "open",
                "yes_bid": 10,
                "yes_ask": 14,
                "volume": 1000,
            },
        ]
        rels = detector.detect_relationships(markets)
        assert len(rels) == 0


class TestScanOpportunities:
    @pytest.mark.asyncio
    async def test_finds_implication_violation(self, strategy, implication_markets):
        # Trump at 55c, Republican at 50c -> violation (A implies B but P(A) > P(B))
        opps = await strategy.scan_opportunities(implication_markets)
        # Should find at least one opp if edge >= 3c
        # Trump mid=55, GOP mid=50, edge=5c >= 3c threshold
        assert len(opps) >= 1
        if opps:
            assert opps[0].side == "yes"  # Buy YES on consequent (underpriced)

    @pytest.mark.asyncio
    async def test_skips_closed(self, strategy, closed_market):
        opps = await strategy.scan_opportunities([closed_market])
        assert len(opps) == 0


class TestCheckExit:
    @pytest.mark.asyncio
    async def test_take_profit(self, strategy):
        position = {"entry_price": 50}
        signal = await strategy.check_exit(position, 55)
        assert signal.should_exit is True
        assert signal.exit_type == "take_profit"

    @pytest.mark.asyncio
    async def test_stop_loss(self, strategy):
        position = {"entry_price": 50}
        signal = await strategy.check_exit(position, 45)
        assert signal.should_exit is True
        assert signal.exit_type == "stop_loss"


class TestHistoricalStats:
    def test_stats(self, strategy):
        stats = strategy.get_historical_stats()
        assert stats["win_rate"] == 0.50
        assert stats["avg_win_cents"] == 6.0


class TestValidateConfig:
    def test_valid(self, strategy):
        valid, _ = strategy.validate_config()
        assert valid is True

    def test_invalid_min_edge(self):
        s = CorrelatedEventArbitrageStrategy({"min_implication_edge_cents": 0})
        valid, _ = s.validate_config()
        assert valid is False
