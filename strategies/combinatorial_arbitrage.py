"""
Combinatorial Arbitrage Strategy

Based on the research paper "Unravelling the Probabilistic Forest: Arbitrage
in Prediction Markets" (arXiv:2508.03474) which documented $40M in realized
arbitrage profits on Polymarket.

Strategy Logic:
    Related markets on prediction platforms should have prices summing to $1
    (100% probability). When they don't, arbitrage opportunities exist:

    - Buy all outcomes for <$1 total -> guaranteed profit
    - Sell all outcomes for >$1 total -> guaranteed profit (if allowed)

Example:
    - Market A: "Trump wins" at 52c
    - Market B: "Biden wins" at 49c
    - Total: $1.01 -> Sell both for guaranteed 1c profit per contract

Key Concepts from Paper:
    1. Market Relationships: Parent/child and mutually exclusive outcomes
    2. Heuristic Filtering: Timeliness, topical similarity, combinatorial relationships
    3. Complexity Management: Avoid O(2^n) explosion with smart filtering
    4. Atomic Execution: All legs must execute or none (all-or-nothing)

Configuration (config.yaml):
    ```yaml
    config:
        min_profit_cents: 2       # Minimum guaranteed profit to execute
        max_exposure_per_arb: 100 # Max capital per arbitrage set
        relationship_types:
            - mutually_exclusive  # Outcomes that should sum to $1
            - parent_child        # Related markets with dependencies
    ```

Expected Value:
    - Win rate: 100% (guaranteed profit when opportunity exists)
    - Risk: Execution risk (partial fills), liquidity risk
    - EV = Guaranteed profit - execution costs
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import Strategy, TradingOpportunity, ExitSignal

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes for Arbitrage
# =============================================================================


class RelationshipType(Enum):
    """Types of market relationships for arbitrage detection."""

    MUTUALLY_EXCLUSIVE = "mutually_exclusive"  # Outcomes sum to 100%
    PARENT_CHILD = "parent_child"              # Related hierarchical markets
    COMPLEMENTARY = "complementary"            # A and NOT A
    MULTI_OUTCOME = "multi_outcome"            # N mutually exclusive outcomes


@dataclass
class MarketOutcome:
    """
    Represents a single tradeable outcome in a market.

    Attributes:
        ticker: Market ticker identifier
        title: Human-readable market title
        outcome: Specific outcome (e.g., "Yes", "No", "Trump", "Biden")
        yes_bid: Best bid price for YES contracts
        yes_ask: Best ask price for YES contracts
        no_bid: Best bid price for NO contracts
        no_ask: Best ask price for NO contracts
        volume: Market volume (liquidity indicator)
        event_ticker: Parent event identifier (for grouping)
        series_ticker: Series identifier (for grouping)
        close_time: When market closes
    """

    ticker: str
    title: str
    outcome: str = ""
    yes_bid: int = 0
    yes_ask: int = 0
    no_bid: int = 0
    no_ask: int = 0
    volume: int = 0
    event_ticker: str = ""
    series_ticker: str = ""
    close_time: Optional[datetime] = None

    @property
    def mid_price(self) -> int:
        """Calculate mid-price from bid/ask."""
        if self.yes_bid and self.yes_ask:
            return (self.yes_bid + self.yes_ask) // 2
        return self.yes_bid or self.yes_ask or 50

    @property
    def spread(self) -> int:
        """Calculate bid-ask spread."""
        if self.yes_bid and self.yes_ask:
            return self.yes_ask - self.yes_bid
        return 10  # Default spread if no data

    @property
    def is_liquid(self) -> bool:
        """Check if market has reasonable liquidity."""
        return self.volume >= 100 and self.spread <= 5


@dataclass
class MarketSet:
    """
    A set of related markets that should have constrained prices.

    For mutually exclusive outcomes, prices should sum to 100 cents.

    Attributes:
        markets: List of related market outcomes
        relationship: Type of relationship between markets
        expected_sum_cents: What the prices should sum to (usually 100)
        confidence: How confident we are in the relationship (0-1)
    """

    markets: List[MarketOutcome] = field(default_factory=list)
    relationship: RelationshipType = RelationshipType.MUTUALLY_EXCLUSIVE
    expected_sum_cents: int = 100
    confidence: float = 1.0

    @property
    def tickers(self) -> List[str]:
        """Get all tickers in this market set."""
        return [m.ticker for m in self.markets]

    @property
    def total_volume(self) -> int:
        """Total volume across all markets."""
        return sum(m.volume for m in self.markets)

    @property
    def min_volume(self) -> int:
        """Minimum volume (liquidity bottleneck)."""
        return min((m.volume for m in self.markets), default=0)

    @property
    def avg_spread(self) -> float:
        """Average bid-ask spread across markets."""
        spreads = [m.spread for m in self.markets]
        return sum(spreads) / len(spreads) if spreads else 10.0

    def is_complete(self) -> bool:
        """Check if set has at least 2 markets."""
        return len(self.markets) >= 2


@dataclass
class ArbitrageLeg:
    """
    A single leg (trade) in an arbitrage opportunity.

    Attributes:
        ticker: Market ticker
        side: "yes" or "no"
        action: "buy" or "sell"
        price_cents: Execution price
        contracts: Number of contracts
    """

    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    price_cents: int
    contracts: int = 1

    @property
    def cost_cents(self) -> int:
        """Cost to execute this leg (positive = outflow)."""
        if self.action == "buy":
            return self.price_cents * self.contracts
        else:  # sell
            return -self.price_cents * self.contracts


@dataclass
class ArbitrageOpportunity:
    """
    A complete arbitrage opportunity with all legs.

    Guaranteed profit = expected_sum - total_buy_cost (for buy-all)
    Or: profit = total_sell_proceeds - expected_sum (for sell-all)

    Attributes:
        legs: All trades needed to capture the arbitrage
        market_set: The related markets involved
        guaranteed_profit_cents: Risk-free profit per set of contracts
        total_cost_cents: Total capital required
        arb_type: "buy_all" or "sell_all"
        execution_risk: Estimated risk of partial fill (0-1)
    """

    legs: List[ArbitrageLeg] = field(default_factory=list)
    market_set: Optional[MarketSet] = None
    guaranteed_profit_cents: int = 0
    total_cost_cents: int = 0
    arb_type: str = "buy_all"  # "buy_all" or "sell_all"
    execution_risk: float = 0.0

    @property
    def profit_percentage(self) -> float:
        """Return on investment percentage."""
        if self.total_cost_cents <= 0:
            return 0.0
        return (self.guaranteed_profit_cents / self.total_cost_cents) * 100

    @property
    def is_profitable(self) -> bool:
        """Check if arbitrage is profitable after costs."""
        return self.guaranteed_profit_cents > 0


# =============================================================================
# Market Relationship Graph
# =============================================================================


class MarketRelationshipGraph:
    """
    Builds and maintains a graph of related markets.

    Uses multiple signals to identify relationships:
    1. Event ticker grouping (same event)
    2. Series ticker grouping (same series)
    3. Title similarity (topical relationship)
    4. Explicit relationship markers

    The graph is used to find market sets that should have
    constrained pricing (e.g., mutually exclusive outcomes).
    """

    def __init__(self):
        """Initialize empty relationship graph."""
        # Map event_ticker -> list of markets
        self.event_groups: Dict[str, List[MarketOutcome]] = {}
        # Map series_ticker -> list of markets
        self.series_groups: Dict[str, List[MarketOutcome]] = {}
        # Map topic_key -> list of markets (from title parsing)
        self.topic_groups: Dict[str, List[MarketOutcome]] = {}
        # All markets by ticker
        self.markets: Dict[str, MarketOutcome] = {}

    def clear(self) -> None:
        """Clear all graph data."""
        self.event_groups.clear()
        self.series_groups.clear()
        self.topic_groups.clear()
        self.markets.clear()

    def add_market(self, market: MarketOutcome) -> None:
        """
        Add a market to the relationship graph.

        Args:
            market: MarketOutcome to add
        """
        self.markets[market.ticker] = market

        # Group by event
        if market.event_ticker:
            if market.event_ticker not in self.event_groups:
                self.event_groups[market.event_ticker] = []
            self.event_groups[market.event_ticker].append(market)

        # Group by series
        if market.series_ticker:
            if market.series_ticker not in self.series_groups:
                self.series_groups[market.series_ticker] = []
            self.series_groups[market.series_ticker].append(market)

        # Extract topic key from title
        topic_key = self._extract_topic_key(market.title)
        if topic_key:
            if topic_key not in self.topic_groups:
                self.topic_groups[topic_key] = []
            self.topic_groups[topic_key].append(market)

    def _extract_topic_key(self, title: str) -> str:
        """
        Extract a topic key from market title for grouping.

        Examples:
            "Will Trump win the 2024 election?" -> "trump_2024_election"
            "Biden wins 2024 presidential race" -> "biden_2024_presidential"
            "S&P 500 above 5000 by Dec?" -> "sp500_5000_dec"

        Args:
            title: Market title string

        Returns:
            Normalized topic key
        """
        if not title:
            return ""

        # Normalize
        title_lower = title.lower()

        # Remove common words
        stop_words = {
            "will", "the", "be", "by", "on", "in", "at", "to", "a", "an",
            "or", "and", "of", "for", "is", "are", "was", "were", "above",
            "below", "between", "yes", "no", "win", "wins", "lose", "loses"
        }

        # Extract key terms
        words = re.findall(r'[a-z0-9]+', title_lower)
        key_words = [w for w in words if w not in stop_words and len(w) > 2]

        # Return first 3 key words as topic key
        return "_".join(key_words[:3]) if key_words else ""

    def find_related_markets(
        self,
        market: MarketOutcome,
        max_related: int = 10,
    ) -> List[MarketOutcome]:
        """
        Find markets related to the given market.

        Searches through event groups, series groups, and topic groups.

        Args:
            market: Market to find relations for
            max_related: Maximum number of related markets to return

        Returns:
            List of related MarketOutcome objects
        """
        related: Set[str] = set()

        # Same event
        if market.event_ticker and market.event_ticker in self.event_groups:
            for m in self.event_groups[market.event_ticker]:
                if m.ticker != market.ticker:
                    related.add(m.ticker)

        # Same series
        if market.series_ticker and market.series_ticker in self.series_groups:
            for m in self.series_groups[market.series_ticker]:
                if m.ticker != market.ticker:
                    related.add(m.ticker)

        # Similar topic
        topic_key = self._extract_topic_key(market.title)
        if topic_key and topic_key in self.topic_groups:
            for m in self.topic_groups[topic_key]:
                if m.ticker != market.ticker:
                    related.add(m.ticker)

        # Convert to market objects and limit
        related_markets = [
            self.markets[ticker]
            for ticker in list(related)[:max_related]
            if ticker in self.markets
        ]

        return related_markets

    def get_event_market_set(self, event_ticker: str) -> Optional[MarketSet]:
        """
        Get all markets in an event as a MarketSet.

        Args:
            event_ticker: Event identifier

        Returns:
            MarketSet if event has multiple markets, None otherwise
        """
        if event_ticker not in self.event_groups:
            return None

        markets = self.event_groups[event_ticker]
        if len(markets) < 2:
            return None

        return MarketSet(
            markets=markets,
            relationship=RelationshipType.MUTUALLY_EXCLUSIVE,
            expected_sum_cents=100,
            confidence=0.9,  # High confidence for same-event markets
        )

    def get_all_market_sets(self) -> List[MarketSet]:
        """
        Get all identifiable market sets from the graph.

        Returns:
            List of MarketSet objects
        """
        market_sets = []

        # Event-based sets (highest confidence)
        for event_ticker, markets in self.event_groups.items():
            if len(markets) >= 2:
                market_sets.append(MarketSet(
                    markets=markets,
                    relationship=RelationshipType.MUTUALLY_EXCLUSIVE,
                    expected_sum_cents=100,
                    confidence=0.95,
                ))

        # Series-based sets (high confidence)
        for series_ticker, markets in self.series_groups.items():
            # Skip if already covered by event groups
            tickers = {m.ticker for m in markets}
            already_covered = any(
                tickers.issubset({m.ticker for m in ms.markets})
                for ms in market_sets
            )

            if not already_covered and len(markets) >= 2:
                market_sets.append(MarketSet(
                    markets=markets,
                    relationship=RelationshipType.MULTI_OUTCOME,
                    expected_sum_cents=100,
                    confidence=0.85,
                ))

        return market_sets


# =============================================================================
# Arbitrage Scanner
# =============================================================================


class ArbitrageScanner:
    """
    Scans market sets for arbitrage opportunities.

    For mutually exclusive outcomes that should sum to 100%:
    - If sum of ask prices < 100: Buy all for guaranteed profit
    - If sum of bid prices > 100: Sell all for guaranteed profit (if allowed)

    Implements heuristic filters from the research paper:
    1. Timeliness: Only active, liquid markets
    2. Topical similarity: Only related topics
    3. Combinatorial: Avoid O(2^n) by using relationship graph
    """

    def __init__(
        self,
        min_profit_cents: int = 2,
        min_liquidity: int = 100,
        max_spread: int = 5,
    ):
        """
        Initialize scanner with thresholds.

        Args:
            min_profit_cents: Minimum profit to consider
            min_liquidity: Minimum volume per market
            max_spread: Maximum bid-ask spread per market
        """
        self.min_profit_cents = min_profit_cents
        self.min_liquidity = min_liquidity
        self.max_spread = max_spread

    def scan_market_set(
        self,
        market_set: MarketSet,
    ) -> Optional[ArbitrageOpportunity]:
        """
        Scan a market set for arbitrage opportunity.

        Checks both buy-all and sell-all strategies.

        Args:
            market_set: Set of related markets to scan

        Returns:
            ArbitrageOpportunity if found, None otherwise
        """
        if not market_set.is_complete():
            return None

        # Apply heuristic filters
        if not self._passes_filters(market_set):
            return None

        # Check buy-all arbitrage
        buy_arb = self._check_buy_all_arbitrage(market_set)
        if buy_arb and buy_arb.guaranteed_profit_cents >= self.min_profit_cents:
            return buy_arb

        # Check sell-all arbitrage (if supported)
        sell_arb = self._check_sell_all_arbitrage(market_set)
        if sell_arb and sell_arb.guaranteed_profit_cents >= self.min_profit_cents:
            return sell_arb

        return None

    def _passes_filters(self, market_set: MarketSet) -> bool:
        """
        Apply heuristic filters to reduce search space.

        Filters:
        1. Timeliness: All markets must be active
        2. Liquidity: Minimum volume threshold
        3. Spread: Maximum bid-ask spread

        Args:
            market_set: Market set to filter

        Returns:
            True if passes all filters
        """
        for market in market_set.markets:
            # Liquidity filter
            if market.volume < self.min_liquidity:
                logger.debug(
                    f"Market {market.ticker} failed liquidity filter: "
                    f"volume={market.volume} < {self.min_liquidity}"
                )
                return False

            # Spread filter
            if market.spread > self.max_spread:
                logger.debug(
                    f"Market {market.ticker} failed spread filter: "
                    f"spread={market.spread} > {self.max_spread}"
                )
                return False

            # Must have valid prices
            if not market.yes_ask or market.yes_ask <= 0:
                logger.debug(f"Market {market.ticker} has no valid ask price")
                return False

        return True

    def _check_buy_all_arbitrage(
        self,
        market_set: MarketSet,
    ) -> Optional[ArbitrageOpportunity]:
        """
        Check for buy-all arbitrage opportunity.

        If sum of YES ask prices < 100, buying all outcomes guarantees
        one will settle at 100 cents, giving risk-free profit.

        Args:
            market_set: Set of mutually exclusive markets

        Returns:
            ArbitrageOpportunity if exists, None otherwise
        """
        legs = []
        total_cost = 0

        for market in market_set.markets:
            # Buy YES at ask price
            ask_price = market.yes_ask
            if not ask_price or ask_price <= 0:
                return None

            legs.append(ArbitrageLeg(
                ticker=market.ticker,
                side="yes",
                action="buy",
                price_cents=ask_price,
                contracts=1,
            ))
            total_cost += ask_price

        # For mutually exclusive outcomes, exactly one settles at 100
        expected_return = market_set.expected_sum_cents
        profit = expected_return - total_cost

        if profit <= 0:
            return None

        # Calculate execution risk based on spreads and liquidity
        execution_risk = self._estimate_execution_risk(market_set)

        return ArbitrageOpportunity(
            legs=legs,
            market_set=market_set,
            guaranteed_profit_cents=profit,
            total_cost_cents=total_cost,
            arb_type="buy_all",
            execution_risk=execution_risk,
        )

    def _check_sell_all_arbitrage(
        self,
        market_set: MarketSet,
    ) -> Optional[ArbitrageOpportunity]:
        """
        Check for sell-all arbitrage opportunity.

        If sum of YES bid prices > 100, selling all outcomes guarantees
        we pay out 100 at settlement, keeping the excess as profit.

        Note: Selling requires having positions or shorting capability.

        Args:
            market_set: Set of mutually exclusive markets

        Returns:
            ArbitrageOpportunity if exists, None otherwise
        """
        legs = []
        total_proceeds = 0

        for market in market_set.markets:
            # Sell YES at bid price
            bid_price = market.yes_bid
            if not bid_price or bid_price <= 0:
                return None

            legs.append(ArbitrageLeg(
                ticker=market.ticker,
                side="yes",
                action="sell",
                price_cents=bid_price,
                contracts=1,
            ))
            total_proceeds += bid_price

        # We receive proceeds now, pay out 100 at settlement
        expected_payout = market_set.expected_sum_cents
        profit = total_proceeds - expected_payout

        if profit <= 0:
            return None

        # Calculate execution risk
        execution_risk = self._estimate_execution_risk(market_set)

        return ArbitrageOpportunity(
            legs=legs,
            market_set=market_set,
            guaranteed_profit_cents=profit,
            total_cost_cents=total_proceeds,  # Capital at risk
            arb_type="sell_all",
            execution_risk=execution_risk,
        )

    def _estimate_execution_risk(self, market_set: MarketSet) -> float:
        """
        Estimate risk of partial fill during execution.

        Based on:
        - Average spread (wider = higher risk)
        - Minimum volume (lower = higher risk)
        - Number of legs (more = higher risk)

        Args:
            market_set: Market set being traded

        Returns:
            Risk score from 0 (no risk) to 1 (certain failure)
        """
        # Spread factor (0-0.4)
        avg_spread = market_set.avg_spread
        spread_risk = min(avg_spread / 10, 0.4)

        # Liquidity factor (0-0.4)
        min_vol = market_set.min_volume
        liquidity_risk = max(0, 0.4 - (min_vol / 2500))

        # Complexity factor (0-0.2) - more legs = more risk
        num_legs = len(market_set.markets)
        complexity_risk = min(num_legs * 0.05, 0.2)

        total_risk = spread_risk + liquidity_risk + complexity_risk
        return min(total_risk, 1.0)


# =============================================================================
# Combinatorial Arbitrage Strategy
# =============================================================================


class CombinatorialArbitrageStrategy(Strategy):
    """
    Combinatorial arbitrage strategy for prediction markets.

    Identifies and exploits pricing inconsistencies in related markets
    where the sum of probabilities should equal 100%.

    Based on research paper: "Unravelling the Probabilistic Forest:
    Arbitrage in Prediction Markets" (arXiv:2508.03474)

    Configuration Parameters:
        - min_profit_cents: Minimum guaranteed profit (default: 2)
        - max_exposure_per_arb: Max capital per arbitrage (default: 100)
        - min_liquidity: Minimum market volume (default: 100)
        - max_spread_cents: Maximum bid-ask spread (default: 5)
        - max_legs: Maximum legs per arbitrage (default: 5)
        - confidence_threshold: Min relationship confidence (default: 0.8)

    Strategy Flow:
        1. Build market relationship graph from available markets
        2. Identify market sets (mutually exclusive outcomes)
        3. Apply heuristic filters (timeliness, liquidity, spread)
        4. Calculate arbitrage opportunities for each set
        5. Return opportunities above minimum profit threshold

    Example:
        >>> config = {"min_profit_cents": 2, "max_exposure_per_arb": 100}
        >>> strategy = CombinatorialArbitrageStrategy(config)
        >>> opportunities = await strategy.scan_opportunities(markets)
        >>> for opp in opportunities:
        ...     print(f"Arb: {opp.reasoning} -> {opp.expected_profit_cents}c")
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize strategy with configuration.

        Args:
            config: Configuration dictionary with parameters:
                - min_profit_cents: Minimum profit threshold (default 2)
                - max_exposure_per_arb: Max capital per arb (default 100)
                - min_liquidity: Min volume filter (default 100)
                - max_spread_cents: Max spread filter (default 5)
                - max_legs: Max number of legs (default 5)
                - confidence_threshold: Min confidence (default 0.8)
        """
        super().__init__(config)

        # Strategy-specific parameters
        self.min_profit_cents = config.get("min_profit_cents", 2)
        self.max_exposure = config.get("max_exposure_per_arb", 100)
        self.min_liquidity = config.get("min_liquidity", 100)
        self.max_spread = config.get("max_spread_cents", 5)
        self.max_legs = config.get("max_legs", 5)
        self.confidence_threshold = config.get("confidence_threshold", 0.8)

        # Internal components
        self.relationship_graph = MarketRelationshipGraph()
        self.scanner = ArbitrageScanner(
            min_profit_cents=self.min_profit_cents,
            min_liquidity=self.min_liquidity,
            max_spread=self.max_spread,
        )

        # Track active arbitrages (for atomic execution)
        self.active_arbitrages: Dict[str, ArbitrageOpportunity] = {}

        logger.info(
            f"CombinatorialArbitrageStrategy initialized: "
            f"min_profit={self.min_profit_cents}c, "
            f"max_exposure={self.max_exposure}c, "
            f"min_liquidity={self.min_liquidity}, "
            f"max_spread={self.max_spread}c"
        )

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "combinatorial_arbitrage"

    @property
    def description(self) -> str:
        """Human-readable strategy description."""
        return (
            f"Combinatorial arbitrage: Exploit pricing inconsistencies "
            f"in related markets (min profit: {self.min_profit_cents}c)"
        )

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan markets for arbitrage opportunities.

        Process:
        1. Convert raw market data to MarketOutcome objects
        2. Build relationship graph
        3. Find market sets with constrained pricing
        4. Scan each set for arbitrage opportunities
        5. Convert to TradingOpportunity format

        Args:
            markets: List of market dictionaries from API
            existing_positions: Dict of ticker -> position (for filtering)

        Returns:
            List of TradingOpportunity objects, sorted by profit
        """
        existing_positions = existing_positions or {}
        opportunities = []

        # Step 1: Build relationship graph
        self._build_relationship_graph(markets)

        # Step 2: Get all market sets
        market_sets = self.relationship_graph.get_all_market_sets()

        logger.info(
            f"[{self.name}] Found {len(market_sets)} market sets "
            f"from {len(markets)} markets"
        )

        # Step 3: Scan each market set for arbitrage
        for market_set in market_sets:
            # Skip low-confidence relationships
            if market_set.confidence < self.confidence_threshold:
                continue

            # Skip if too many legs (complexity explosion)
            if len(market_set.markets) > self.max_legs:
                logger.debug(
                    f"Skipping market set with {len(market_set.markets)} legs "
                    f"(max: {self.max_legs})"
                )
                continue

            # Skip if any market already has position
            if any(m.ticker in existing_positions for m in market_set.markets):
                continue

            # Scan for arbitrage
            arb = self.scanner.scan_market_set(market_set)

            if arb and arb.is_profitable:
                opp = self._convert_to_trading_opportunity(arb)
                if opp:
                    opportunities.append(opp)

        # Sort by guaranteed profit (best first)
        opportunities.sort(
            key=lambda x: x.expected_profit_cents,
            reverse=True,
        )

        logger.info(
            f"[{self.name}] Found {len(opportunities)} arbitrage opportunities"
        )

        return opportunities

    def _build_relationship_graph(self, markets: List[Dict]) -> None:
        """
        Build market relationship graph from raw market data.

        Args:
            markets: List of market dictionaries from API
        """
        self.relationship_graph.clear()

        for market in markets:
            # Skip non-open markets
            if market.get("status") not in ("open", "active"):
                continue

            # Parse close time
            close_time = None
            close_time_str = market.get("close_time") or market.get("expiration_time")
            if close_time_str:
                try:
                    if isinstance(close_time_str, str):
                        close_time = datetime.fromisoformat(
                            close_time_str.replace("Z", "+00:00")
                        )
                except (ValueError, TypeError):
                    pass

            # Create MarketOutcome
            outcome = MarketOutcome(
                ticker=market.get("ticker", ""),
                title=market.get("title", ""),
                outcome=market.get("outcome", ""),
                yes_bid=market.get("yes_bid", 0),
                yes_ask=market.get("yes_ask", 0),
                no_bid=market.get("no_bid", 0),
                no_ask=market.get("no_ask", 0),
                volume=market.get("volume", 0) or market.get("volume_24h", 0),
                event_ticker=market.get("event_ticker", ""),
                series_ticker=market.get("series_ticker", ""),
                close_time=close_time,
            )

            self.relationship_graph.add_market(outcome)

    def _convert_to_trading_opportunity(
        self,
        arb: ArbitrageOpportunity,
    ) -> Optional[TradingOpportunity]:
        """
        Convert ArbitrageOpportunity to TradingOpportunity.

        Creates a TradingOpportunity that represents the first leg
        of the arbitrage, with metadata containing all other legs.

        Args:
            arb: ArbitrageOpportunity to convert

        Returns:
            TradingOpportunity or None if invalid
        """
        if not arb.legs or not arb.market_set:
            return None

        # Use first leg as primary trade
        primary_leg = arb.legs[0]
        primary_market = arb.market_set.markets[0]

        # Calculate score based on profit and risk
        # Higher profit = better, higher risk = worse
        profit_score = min(arb.guaranteed_profit_cents * 10, 50)  # Max 50 points
        risk_penalty = arb.execution_risk * 30  # Max 30 point penalty
        liquidity_score = min(arb.market_set.min_volume / 100, 20)  # Max 20 points

        total_score = max(0, min(100, profit_score - risk_penalty + liquidity_score))

        # Build reasoning string
        market_tickers = ", ".join(arb.market_set.tickers)
        reasoning = (
            f"Arbitrage opportunity ({arb.arb_type}): "
            f"Markets [{market_tickers}] sum to "
            f"{arb.total_cost_cents}c (expected: 100c). "
            f"Guaranteed profit: {arb.guaranteed_profit_cents}c. "
            f"Execution risk: {arb.execution_risk:.1%}"
        )

        # Generate unique arb ID for tracking
        arb_id = f"arb_{hash(tuple(arb.market_set.tickers))}"
        self.active_arbitrages[arb_id] = arb

        return TradingOpportunity(
            ticker=primary_leg.ticker,
            title=primary_market.title,
            side=primary_leg.side,
            entry_price_cents=primary_leg.price_cents,
            current_yes_price=primary_market.yes_bid or 50,
            current_no_price=primary_market.no_bid or 50,
            volume=arb.market_set.min_volume,
            score=total_score,
            reasoning=reasoning,
            expected_profit_cents=arb.guaranteed_profit_cents,
            max_loss_cents=0,  # Arbitrage has no loss if executed properly
            strategy_name=self.name,
            metadata={
                "arb_id": arb_id,
                "arb_type": arb.arb_type,
                "all_legs": [
                    {
                        "ticker": leg.ticker,
                        "side": leg.side,
                        "action": leg.action,
                        "price_cents": leg.price_cents,
                    }
                    for leg in arb.legs
                ],
                "market_tickers": arb.market_set.tickers,
                "total_cost_cents": arb.total_cost_cents,
                "execution_risk": arb.execution_risk,
                "relationship_type": arb.market_set.relationship.value,
                "confidence": arb.market_set.confidence,
            },
        )

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """
        Check if arbitrage position should be exited.

        For arbitrage positions:
        - Hold until settlement (guaranteed profit)
        - Exit early if execution was incomplete
        - Exit if approaching expiry with unfilled legs

        Args:
            position: Position data with entry_price, side, entry_time
            current_price: Current market price for our side
            market_data: Optional additional market data

        Returns:
            ExitSignal with recommendation
        """
        entry_price = position.get("entry_price", 50)
        arb_id = position.get("metadata", {}).get("arb_id")

        # Check if this is part of a tracked arbitrage
        if arb_id and arb_id in self.active_arbitrages:
            arb = self.active_arbitrages[arb_id]

            # Check if all legs were filled
            all_legs = position.get("metadata", {}).get("all_legs", [])
            filled_legs = position.get("metadata", {}).get("filled_legs", [])

            if len(filled_legs) < len(all_legs):
                # Incomplete arbitrage - need to evaluate
                return ExitSignal(
                    should_exit=True,
                    reason="Incomplete arbitrage execution - exiting partial position",
                    exit_type="manual",
                    current_price_cents=current_price,
                    pnl_cents=current_price - entry_price,
                    urgency=0.7,
                )

        # For complete arbitrage, hold until settlement
        pnl_cents = current_price - entry_price

        # Check if near expiry
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

                    time_to_close = (
                        close_time - datetime.now(close_time.tzinfo)
                    ).total_seconds()

                    # If very close to settlement, let it ride
                    if 0 < time_to_close < 60:
                        return ExitSignal(
                            should_exit=False,
                            reason=f"Near settlement ({int(time_to_close)}s), holding for guaranteed profit",
                            exit_type="hold",
                            current_price_cents=current_price,
                            pnl_cents=pnl_cents,
                            urgency=0.0,
                        )
                except (ValueError, TypeError):
                    pass

        # Default: hold the arbitrage position
        return ExitSignal(
            should_exit=False,
            reason=f"Arbitrage position - holding for guaranteed profit. Current P&L: {pnl_cents:+d}c",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def get_arbitrage_legs(self, arb_id: str) -> Optional[List[ArbitrageLeg]]:
        """
        Get all legs for an arbitrage opportunity.

        Used by execution engine to place all orders atomically.

        Args:
            arb_id: Arbitrage identifier from metadata

        Returns:
            List of ArbitrageLeg objects, or None if not found
        """
        if arb_id not in self.active_arbitrages:
            return None
        return self.active_arbitrages[arb_id].legs

    def calculate_guaranteed_profit(
        self,
        positions: List[Dict[str, Any]],
    ) -> float:
        """
        Calculate guaranteed profit from a set of arbitrage positions.

        For complete arbitrage (all legs filled):
        - Profit = 100 - sum(entry_prices) for buy-all
        - Profit = sum(entry_prices) - 100 for sell-all

        Args:
            positions: List of position dictionaries with entry prices

        Returns:
            Guaranteed profit in cents (0 if incomplete)
        """
        if not positions:
            return 0.0

        # Sum entry prices
        total_cost = sum(p.get("entry_price", 0) for p in positions)

        # Determine arb type from first position
        arb_type = positions[0].get("metadata", {}).get("arb_type", "buy_all")

        if arb_type == "buy_all":
            # We paid total_cost, will receive 100 at settlement
            return 100 - total_cost
        else:  # sell_all
            # We received total_cost, will pay 100 at settlement
            return total_cost - 100

    def _get_prior_stats(self) -> Dict[str, float]:
        """
        Get hardcoded prior statistics for Kelly calculation.

        For arbitrage:
        - Win rate: Near 100% (fails only on execution issues)
        - Average win: min_profit_cents (conservative)
        - Average loss: Near 0 (should not lose if executed correctly)

        Returns:
            Dict with win_rate, avg_win_cents, avg_loss_cents
        """
        # Structural edge preserved — arb mispricing is mathematical, not statistical
        return {
            "win_rate": 0.80,
            "avg_win_cents": float(self.min_profit_cents),
            "avg_loss_cents": 2.0,
        }

    def validate_config(self) -> tuple[bool, str]:
        """Validate arbitrage-specific configuration."""
        valid, error = super().validate_config()
        if not valid:
            return valid, error

        if self.min_profit_cents < 1:
            return False, "min_profit_cents must be at least 1"

        if self.max_exposure < self.min_profit_cents:
            return False, "max_exposure must be >= min_profit_cents"

        if self.max_legs < 2:
            return False, "max_legs must be at least 2 for arbitrage"

        if not (0 < self.confidence_threshold <= 1):
            return False, "confidence_threshold must be between 0 and 1"

        return True, ""


# =============================================================================
# Utility Functions
# =============================================================================


def find_related_markets(markets: List[Dict]) -> List[MarketSet]:
    """
    Find groups of related markets from a list.

    Convenience function that builds a relationship graph and
    returns all identified market sets.

    Args:
        markets: List of market dictionaries from API

    Returns:
        List of MarketSet objects
    """
    graph = MarketRelationshipGraph()

    for market in markets:
        if market.get("status") not in ("open", "active"):
            continue

        outcome = MarketOutcome(
            ticker=market.get("ticker", ""),
            title=market.get("title", ""),
            yes_bid=market.get("yes_bid", 0),
            yes_ask=market.get("yes_ask", 0),
            no_bid=market.get("no_bid", 0),
            no_ask=market.get("no_ask", 0),
            volume=market.get("volume", 0),
            event_ticker=market.get("event_ticker", ""),
            series_ticker=market.get("series_ticker", ""),
        )
        graph.add_market(outcome)

    return graph.get_all_market_sets()


def check_arbitrage_opportunity(market_set: MarketSet) -> Optional[ArbitrageOpportunity]:
    """
    Check a market set for arbitrage opportunity.

    Convenience function that creates a scanner and checks
    both buy-all and sell-all strategies.

    Args:
        market_set: Set of related markets

    Returns:
        ArbitrageOpportunity if found, None otherwise
    """
    scanner = ArbitrageScanner(min_profit_cents=1)
    return scanner.scan_market_set(market_set)


def calculate_guaranteed_profit(positions: List[Dict[str, Any]]) -> float:
    """
    Calculate guaranteed profit from arbitrage positions.

    Args:
        positions: List of position dictionaries

    Returns:
        Guaranteed profit in cents
    """
    if not positions:
        return 0.0

    total_cost = sum(p.get("entry_price", 0) for p in positions)
    arb_type = positions[0].get("metadata", {}).get("arb_type", "buy_all")

    if arb_type == "buy_all":
        return 100 - total_cost
    else:
        return total_cost - 100
