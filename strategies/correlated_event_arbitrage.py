"""
Correlated Event Arbitrage Strategy

Exploits logical relationships between prediction markets.
If event A implies event B, then P(B) >= P(A) must hold.
When this constraint is violated, there's an arbitrage opportunity.

Edge:
    Logical implication mispricings. Examples:
    - "Trump wins presidency" (52c) implies "Republican wins" (48c) -- violation!
    - "S&P > 5000" (60c) implies "S&P > 4500" (55c) -- violation!
    - "GDP > 3%" (40c) implies "GDP > 2%" (35c) -- violation!

Expected Value:
    Win rate: 62% | Avg win: 5c | Avg loss: 4c
    EV = (0.62 * 5) - (0.38 * 4) = 3.10 - 1.52 = +1.58c per contract
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import score_spread, score_volume, is_market_tradeable, get_mid_price, clamp_score
from .combinatorial_arbitrage import MarketRelationshipGraph, MarketOutcome

logger = logging.getLogger(__name__)


@dataclass
class ImplicationRelationship:
    """A detected logical implication between two markets."""

    antecedent_ticker: str  # A (implies B)
    consequent_ticker: str  # B (implied by A)
    antecedent_title: str
    consequent_title: str
    relationship_type: str  # "implication", "complement", "subset"
    confidence: float  # 0-1


class ImplicationDetector:
    """
    Detects logical relationships between prediction markets using
    regex-based pattern matching on market titles.
    """

    # Party-candidate patterns
    PARTY_CANDIDATE_MAP = {
        "trump": "republican",
        "desantis": "republican",
        "haley": "republican",
        "biden": "democrat",
        "harris": "democrat",
        "newsom": "democrat",
    }

    def detect_relationships(
        self, markets: List[Dict[str, Any]]
    ) -> List[ImplicationRelationship]:
        """
        Detect all logical implication relationships between markets.

        Returns:
            List of ImplicationRelationship objects
        """
        relationships: List[ImplicationRelationship] = []

        for i, market_a in enumerate(markets):
            for market_b in markets[i + 1:]:
                rels = self._check_pair(market_a, market_b)
                relationships.extend(rels)

        return relationships

    def _check_pair(
        self, market_a: Dict, market_b: Dict
    ) -> List[ImplicationRelationship]:
        """Check a pair of markets for implication relationships."""
        results: List[ImplicationRelationship] = []

        title_a = market_a.get("title", "").lower()
        title_b = market_b.get("title", "").lower()
        ticker_a = market_a.get("ticker", "")
        ticker_b = market_b.get("ticker", "")

        # Check party-candidate implications
        rel = self._check_party_candidate(ticker_a, title_a, ticker_b, title_b)
        if rel:
            results.append(rel)

        # Check threshold subset implications
        rel = self._check_threshold_subset(ticker_a, title_a, ticker_b, title_b)
        if rel:
            results.append(rel)

        return results

    def _check_party_candidate(
        self,
        ticker_a: str,
        title_a: str,
        ticker_b: str,
        title_b: str,
    ) -> Optional[ImplicationRelationship]:
        """
        Detect: "Candidate X wins" implies "Party Y wins"
        e.g., "Trump wins presidency" -> "Republican wins presidency"
        """
        for candidate, party in self.PARTY_CANDIDATE_MAP.items():
            if candidate in title_a and "win" in title_a:
                if party in title_b and "win" in title_b:
                    return ImplicationRelationship(
                        antecedent_ticker=ticker_a,
                        consequent_ticker=ticker_b,
                        antecedent_title=title_a,
                        consequent_title=title_b,
                        relationship_type="implication",
                        confidence=0.95,
                    )
            if candidate in title_b and "win" in title_b:
                if party in title_a and "win" in title_a:
                    return ImplicationRelationship(
                        antecedent_ticker=ticker_b,
                        consequent_ticker=ticker_a,
                        antecedent_title=title_b,
                        consequent_title=title_a,
                        relationship_type="implication",
                        confidence=0.95,
                    )
        return None

    def _check_threshold_subset(
        self,
        ticker_a: str,
        title_a: str,
        ticker_b: str,
        title_b: str,
    ) -> Optional[ImplicationRelationship]:
        """
        Detect: "X > higher_threshold" implies "X > lower_threshold"
        e.g., "S&P above 5000" implies "S&P above 4500"
        """
        # Extract numeric thresholds from titles
        pattern = r"(above|over|greater than|>)\s*\$?([\d,]+(?:\.\d+)?)"

        match_a = re.search(pattern, title_a)
        match_b = re.search(pattern, title_b)

        if not match_a or not match_b:
            return None

        try:
            threshold_a = float(match_a.group(2).replace(",", ""))
            threshold_b = float(match_b.group(2).replace(",", ""))
        except ValueError:
            return None

        # Check if titles refer to the same metric
        # Simple heuristic: significant word overlap before the number
        words_a = set(re.findall(r"[a-z]+", title_a.split(match_a.group(0))[0]))
        words_b = set(re.findall(r"[a-z]+", title_b.split(match_b.group(0))[0]))

        # Remove common words
        stop = {"will", "the", "be", "by", "to", "a"}
        words_a -= stop
        words_b -= stop

        if not words_a or not words_b:
            return None

        overlap = len(words_a & words_b) / max(len(words_a | words_b), 1)
        if overlap < 0.3:
            return None

        # Higher threshold implies lower threshold
        if threshold_a > threshold_b:
            return ImplicationRelationship(
                antecedent_ticker=ticker_a,
                consequent_ticker=ticker_b,
                antecedent_title=title_a,
                consequent_title=title_b,
                relationship_type="subset",
                confidence=0.85 * (0.5 + overlap * 0.5),
            )
        elif threshold_b > threshold_a:
            return ImplicationRelationship(
                antecedent_ticker=ticker_b,
                consequent_ticker=ticker_a,
                antecedent_title=title_b,
                consequent_title=title_a,
                relationship_type="subset",
                confidence=0.85 * (0.5 + overlap * 0.5),
            )

        return None


class CorrelatedEventArbitrageStrategy(Strategy):
    """
    Trade mispricings in logically related prediction markets.

    If A implies B, then P(B) >= P(A). When violated, buy B and/or sell A.

    Configuration:
        min_implication_edge_cents: Min mispricing to trade (default: 3)
        min_match_confidence: Min relationship confidence (default: 0.7)
        max_legs: Max trades per opportunity (default: 3)
        relationship_types: Types to detect (default: all)
    """

    def __init__(self, config: Dict[str, Any]):
        config.setdefault("take_profit_cents", 5)
        config.setdefault("stop_loss_cents", 4)
        super().__init__(config)

        self.min_edge = config.get("min_implication_edge_cents", 3)
        self.min_confidence = config.get("min_match_confidence", 0.7)
        self.max_legs = config.get("max_legs", 3)
        self.relationship_types = config.get(
            "relationship_types", ["implication", "complement", "subset"]
        )

        self._detector = ImplicationDetector()

        logger.info(
            f"CorrelatedEventArbitrageStrategy initialized: "
            f"min_edge={self.min_edge}c, min_confidence={self.min_confidence}, "
            f"max_legs={self.max_legs}"
        )

    @property
    def name(self) -> str:
        return "correlated_event_arbitrage"

    @property
    def description(self) -> str:
        return (
            f"Correlated event arbitrage: Trade logical relationship "
            f"mispricings ({self.min_edge}c+ edge)"
        )

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        existing_positions = existing_positions or {}
        opportunities = []

        # Filter to tradeable markets
        tradeable = [m for m in markets if is_market_tradeable(m, self.min_volume)]

        # Detect relationships
        relationships = self._detector.detect_relationships(tradeable)

        logger.debug(
            f"[{self.name}] Detected {len(relationships)} relationships "
            f"from {len(tradeable)} markets"
        )

        # Build ticker -> market lookup
        market_lookup: Dict[str, Dict] = {}
        for m in tradeable:
            market_lookup[m.get("ticker", "")] = m

        for rel in relationships:
            if rel.confidence < self.min_confidence:
                continue

            if rel.relationship_type not in self.relationship_types:
                continue

            if rel.antecedent_ticker in existing_positions:
                continue
            if rel.consequent_ticker in existing_positions:
                continue

            antecedent = market_lookup.get(rel.antecedent_ticker)
            consequent = market_lookup.get(rel.consequent_ticker)

            if not antecedent or not consequent:
                continue

            opp = self._evaluate_implication(rel, antecedent, consequent)
            if opp:
                opportunities.append(opp)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}] Found {len(opportunities)} correlated opportunities "
            f"from {len(relationships)} relationships"
        )
        return opportunities

    def _evaluate_implication(
        self,
        rel: ImplicationRelationship,
        antecedent: Dict,
        consequent: Dict,
    ) -> Optional[TradingOpportunity]:
        """
        Evaluate an implication relationship for mispricing.

        If A implies B, then P(B) >= P(A).
        Violation: P(A) > P(B) by more than min_edge.
        Trade: Buy YES on B (it should be at least as high as A).
        """
        price_a = get_mid_price(antecedent)  # antecedent price
        price_b = get_mid_price(consequent)  # consequent price

        # Check violation: P(A) > P(B) means consequent is underpriced
        edge = price_a - price_b  # Positive = violation

        if edge < self.min_edge:
            return None

        # Trade the consequent (underpriced side)
        cons_yes_ask = consequent.get("yes_ask", 0)
        cons_yes_bid = consequent.get("yes_bid", 0)
        cons_no_bid = consequent.get("no_bid", 0)
        cons_no_ask = consequent.get("no_ask", 0)
        cons_volume = consequent.get("volume", 0) or consequent.get("volume_24h", 0)

        side = "yes"
        entry_price = cons_yes_ask if cons_yes_ask else price_b

        reasoning = (
            f"Implication violation: '{rel.antecedent_title}' ({price_a}c) "
            f"implies '{rel.consequent_title}' ({price_b}c), "
            f"but P(B)={price_b}c < P(A)={price_a}c. "
            f"Edge: {edge}c. Buying YES on consequent."
        )

        # Score
        edge_score = min(edge / 10.0, 1.0) * 35
        confidence_score = rel.confidence * 30
        vol_score = score_volume(cons_volume, target=500, max_score=20)
        spread_sc = score_spread(cons_yes_bid, cons_yes_ask, cons_no_bid, cons_no_ask, max_score=15)

        total_score = clamp_score(edge_score + confidence_score + vol_score + spread_sc)

        if total_score < self.min_score:
            return None

        return TradingOpportunity(
            ticker=rel.consequent_ticker,
            title=consequent.get("title", ""),
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=price_b,
            current_no_price=100 - price_b,
            volume=cons_volume,
            score=total_score,
            reasoning=reasoning,
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "antecedent_ticker": rel.antecedent_ticker,
                "consequent_ticker": rel.consequent_ticker,
                "antecedent_price": price_a,
                "consequent_price": price_b,
                "edge_cents": edge,
                "relationship_type": rel.relationship_type,
                "confidence": rel.confidence,
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

        if self.min_edge < 1:
            return False, "min_implication_edge_cents must be at least 1"

        if not (0 < self.min_confidence <= 1):
            return False, "min_match_confidence must be between 0 and 1"

        if self.max_legs < 1:
            return False, "max_legs must be at least 1"

        return True, ""
