"""
Polymarket Market Implementation (Read-Only)

Read-only API client for Polymarket prediction markets. Used as a data source
for cross-platform arbitrage signals. No order placement capability.

Polymarket uses the Gamma API for market data:
- Base URL: https://gamma-api.polymarket.com
- Public endpoints (no authentication needed)
- Rate limit: ~1000 calls/hour for read operations

Data Flow:
    Polymarket (data source) -> Compare with Kalshi -> Generate signals -> Trade on Kalshi

Design Notes:
    - This client is READ-ONLY - trading methods raise NotImplementedError
    - Market data is normalized to match Kalshi format for easy comparison
    - Includes market matching utilities for cross-platform correlation
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
import asyncio

try:
    import httpx
except ImportError:
    httpx = None

from .base import Market

logger = logging.getLogger(__name__)


# =============================================================================
# Constants and Configuration
# =============================================================================

POLYMARKET_GAMMA_API_BASE = "https://gamma-api.polymarket.com"

# Common topic keywords for market matching
TOPIC_KEYWORDS = {
    "politics": ["trump", "biden", "election", "president", "congress", "senate", "house", "governor"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain"],
    "finance": ["fed", "interest", "rate", "inflation", "gdp", "unemployment", "stock", "s&p", "nasdaq"],
    "sports": ["nfl", "nba", "mlb", "nhl", "soccer", "football", "basketball", "baseball"],
    "entertainment": ["oscars", "emmy", "grammy", "movie", "film", "tv"],
    "tech": ["ai", "openai", "google", "apple", "microsoft", "meta", "tesla"],
    "world": ["ukraine", "russia", "china", "israel", "gaza", "war", "conflict"],
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class MarketMatchScore:
    """
    Score for how well two markets match across platforms.

    Attributes:
        polymarket_id: Polymarket market ID
        kalshi_ticker: Kalshi market ticker
        title_similarity: Title text similarity (0-1)
        topic_match: Whether topics align (0-1)
        outcome_match: Whether outcomes match (0-1)
        expiry_match: Whether expiry dates align (0-1)
        total_score: Combined match score (0-1)
        matched_keywords: Keywords found in both markets
    """
    polymarket_id: str
    kalshi_ticker: str
    title_similarity: float = 0.0
    topic_match: float = 0.0
    outcome_match: float = 0.0
    expiry_match: float = 0.0
    total_score: float = 0.0
    matched_keywords: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Calculate total score from components."""
        # Weighted average of match components
        weights = {
            "title": 0.4,
            "topic": 0.25,
            "outcome": 0.25,
            "expiry": 0.1,
        }
        self.total_score = (
            weights["title"] * self.title_similarity +
            weights["topic"] * self.topic_match +
            weights["outcome"] * self.outcome_match +
            weights["expiry"] * self.expiry_match
        )


@dataclass
class MatchedMarketPair:
    """
    A pair of matched markets across Polymarket and Kalshi.

    Attributes:
        polymarket_market: Normalized Polymarket market data
        kalshi_market: Normalized Kalshi market data (if found)
        match_score: Matching confidence score
        price_diff_cents: YES price difference (Kalshi - Polymarket)
        is_arbitrage_candidate: Whether price diff exceeds threshold
    """
    polymarket_market: Dict[str, Any]
    kalshi_market: Optional[Dict[str, Any]] = None
    match_score: Optional[MarketMatchScore] = None
    price_diff_cents: int = 0
    is_arbitrage_candidate: bool = False


# =============================================================================
# Market Matching Utilities
# =============================================================================


class MarketMatcher:
    """
    Fuzzy matching engine for cross-platform market correlation.

    Uses multiple signals to match markets:
    1. Title similarity (fuzzy string matching)
    2. Topic/keyword extraction
    3. Outcome type matching (binary, multi-choice)
    4. Expiry date proximity
    """

    def __init__(
        self,
        min_match_score: float = 0.6,
        max_expiry_diff_days: int = 7,
    ):
        """
        Initialize market matcher.

        Args:
            min_match_score: Minimum score to consider a match (0-1)
            max_expiry_diff_days: Max days between expiry dates
        """
        self.min_match_score = min_match_score
        self.max_expiry_diff_days = max_expiry_diff_days

        # Cache of matched pairs to avoid re-matching
        self._match_cache: Dict[str, MatchedMarketPair] = {}

    def clear_cache(self) -> None:
        """Clear the match cache."""
        self._match_cache.clear()

    def find_best_match(
        self,
        polymarket_market: Dict[str, Any],
        kalshi_markets: List[Dict[str, Any]],
    ) -> Optional[MatchedMarketPair]:
        """
        Find the best Kalshi match for a Polymarket market.

        Args:
            polymarket_market: Normalized Polymarket market data
            kalshi_markets: List of Kalshi markets to search

        Returns:
            MatchedMarketPair with best match, or None if no good match
        """
        poly_id = polymarket_market.get("ticker", "")

        # Check cache
        if poly_id in self._match_cache:
            return self._match_cache[poly_id]

        best_match = None
        best_score = 0.0

        for kalshi_market in kalshi_markets:
            score = self._calculate_match_score(polymarket_market, kalshi_market)

            if score.total_score > best_score and score.total_score >= self.min_match_score:
                best_score = score.total_score
                best_match = MatchedMarketPair(
                    polymarket_market=polymarket_market,
                    kalshi_market=kalshi_market,
                    match_score=score,
                )

        if best_match:
            # Calculate price difference
            poly_price = polymarket_market.get("yes_bid", 0) or polymarket_market.get("last_price", 0)
            kalshi_price = best_match.kalshi_market.get("yes_bid", 0) or best_match.kalshi_market.get("last_price", 0)
            best_match.price_diff_cents = kalshi_price - poly_price

            # Cache the match
            self._match_cache[poly_id] = best_match

        return best_match

    def _calculate_match_score(
        self,
        poly_market: Dict[str, Any],
        kalshi_market: Dict[str, Any],
    ) -> MarketMatchScore:
        """
        Calculate how well two markets match.

        Args:
            poly_market: Polymarket market data
            kalshi_market: Kalshi market data

        Returns:
            MarketMatchScore with component scores
        """
        poly_title = poly_market.get("title", "").lower()
        kalshi_title = kalshi_market.get("title", "").lower()

        # 1. Title similarity using sequence matcher
        title_sim = SequenceMatcher(None, poly_title, kalshi_title).ratio()

        # 2. Topic/keyword matching
        poly_keywords = self._extract_keywords(poly_title)
        kalshi_keywords = self._extract_keywords(kalshi_title)
        common_keywords = poly_keywords & kalshi_keywords

        if poly_keywords or kalshi_keywords:
            keyword_union = poly_keywords | kalshi_keywords
            topic_match = len(common_keywords) / len(keyword_union) if keyword_union else 0
        else:
            topic_match = 0.0

        # 3. Outcome matching (both binary?)
        poly_binary = self._is_binary_market(poly_market)
        kalshi_binary = self._is_binary_market(kalshi_market)
        outcome_match = 1.0 if poly_binary == kalshi_binary else 0.5

        # 4. Expiry date proximity
        expiry_match = self._calculate_expiry_match(poly_market, kalshi_market)

        return MarketMatchScore(
            polymarket_id=poly_market.get("ticker", ""),
            kalshi_ticker=kalshi_market.get("ticker", ""),
            title_similarity=title_sim,
            topic_match=topic_match,
            outcome_match=outcome_match,
            expiry_match=expiry_match,
            matched_keywords=list(common_keywords),
        )

    def _extract_keywords(self, text: str) -> set:
        """Extract topic keywords from market title."""
        keywords = set()
        text_lower = text.lower()

        # Extract from predefined topics
        for topic, topic_keywords in TOPIC_KEYWORDS.items():
            for kw in topic_keywords:
                if kw in text_lower:
                    keywords.add(kw)

        # Extract years (2024, 2025, etc.)
        years = re.findall(r'\b20\d{2}\b', text)
        keywords.update(years)

        # Extract percentages and numbers that might be thresholds
        numbers = re.findall(r'\b\d+(?:\.\d+)?(?:%|k|m|b)?\b', text_lower)
        keywords.update(numbers[:3])  # Limit to avoid noise

        return keywords

    def _is_binary_market(self, market: Dict[str, Any]) -> bool:
        """Check if market is binary (yes/no) vs multi-outcome."""
        # Check if NO price exists and is complement of YES
        yes_price = market.get("yes_bid", 0) or market.get("last_price", 0)
        no_price = market.get("no_bid", 0)

        # Binary markets have YES + NO roughly equal to 100
        if yes_price and no_price:
            total = yes_price + no_price
            return 90 <= total <= 110

        # Check outcomes field if available
        outcomes = market.get("outcomes", [])
        if isinstance(outcomes, str):
            try:
                import json
                outcomes = json.loads(outcomes)
            except (json.JSONDecodeError, TypeError):
                pass

        return len(outcomes) <= 2 if isinstance(outcomes, list) else True

    def _calculate_expiry_match(
        self,
        poly_market: Dict[str, Any],
        kalshi_market: Dict[str, Any],
    ) -> float:
        """Calculate expiry date proximity score."""
        poly_expiry = poly_market.get("expiration_time") or poly_market.get("close_time")
        kalshi_expiry = kalshi_market.get("expiration_time") or kalshi_market.get("close_time")

        if not poly_expiry or not kalshi_expiry:
            return 0.5  # Unknown, give neutral score

        try:
            # Parse dates
            if isinstance(poly_expiry, str):
                poly_dt = datetime.fromisoformat(poly_expiry.replace("Z", "+00:00"))
            else:
                poly_dt = poly_expiry

            if isinstance(kalshi_expiry, str):
                kalshi_dt = datetime.fromisoformat(kalshi_expiry.replace("Z", "+00:00"))
            else:
                kalshi_dt = kalshi_expiry

            # Calculate day difference
            diff_days = abs((poly_dt - kalshi_dt).days)

            if diff_days <= self.max_expiry_diff_days:
                # Linear decay within threshold
                return 1.0 - (diff_days / self.max_expiry_diff_days)
            else:
                return 0.0

        except (ValueError, TypeError, AttributeError):
            return 0.5  # Parse error, neutral score


# =============================================================================
# Polymarket Client
# =============================================================================


class PolymarketMarket(Market):
    """
    Read-only Polymarket market client.

    Fetches market data from Polymarket's Gamma API for use as signals
    in cross-platform trading. Does NOT support order placement.

    Example:
        >>> market = PolymarketMarket({})
        >>> await market.connect()
        >>> markets = await market.get_open_markets()
        >>> for m in markets:
        ...     print(f"{m['title']}: {m['yes_bid']}c")
    """

    def __init__(self, config: Dict[str, Any], client: Any = None):
        """
        Initialize Polymarket client.

        Args:
            config: Configuration dict with optional:
                - base_url: API base URL (default: Gamma API)
                - timeout: Request timeout seconds (default: 30)
                - cache_ttl: Cache TTL seconds (default: 60)
            client: Optional httpx client for testing
        """
        super().__init__(config, client)

        self.base_url = config.get("base_url", POLYMARKET_GAMMA_API_BASE)
        self.timeout = config.get("timeout", 30)
        self.cache_ttl = config.get("cache_ttl", 60)

        # HTTP client
        self._http_client: Optional[httpx.AsyncClient] = client
        self._connected = False

        # Market data cache
        self._market_cache: Dict[str, Dict] = {}
        self._cache_timestamp: Optional[datetime] = None

        # Market matcher for cross-platform correlation
        self.matcher = MarketMatcher(
            min_match_score=config.get("min_match_score", 0.6),
            max_expiry_diff_days=config.get("max_expiry_diff_days", 7),
        )

        logger.info(f"PolymarketMarket initialized (base_url={self.base_url})")

    @property
    def name(self) -> str:
        """Market identifier."""
        return "polymarket"

    async def connect(self) -> None:
        """
        Initialize HTTP client for API requests.

        No authentication needed for public read endpoints.
        """
        if self._connected:
            return

        if httpx is None:
            raise ImportError("httpx package required: pip install httpx")

        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "kalshi-trading-bot/1.0",
                },
            )

        self._connected = True
        logger.info("Polymarket client connected")

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._http_client and self._connected:
            await self._http_client.aclose()
            self._http_client = None
            self._connected = False
            logger.info("Polymarket client disconnected")

    async def get_open_markets(
        self,
        series: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
    ) -> List[Dict]:
        """
        Fetch open Polymarket markets.

        Args:
            series: Optional tag filter (maps to Polymarket tags)
            status: Market status filter ("open" = active & not closed)
            limit: Maximum markets to return

        Returns:
            List of normalized market dicts matching Kalshi format
        """
        if not self._connected:
            await self.connect()

        # Check cache
        if self._is_cache_valid():
            return list(self._market_cache.values())[:limit]

        try:
            # Build query parameters
            params = {
                "active": "true",
                "closed": "false" if status == "open" else "true",
                "limit": min(limit, 100),  # Polymarket max is 100 per page
                "order": "volume24hr",
                "ascending": "false",
            }

            # Add tag filter if specified
            if series and series != "*":
                params["tag"] = series

            # Fetch events (contains nested markets)
            response = await self._http_client.get("/events", params=params)
            response.raise_for_status()

            events = response.json()

            # Normalize all markets from events
            normalized_markets = []
            for event in events:
                markets = event.get("markets", [])
                for market in markets:
                    normalized = self._normalize_market(market, event)
                    if normalized:
                        normalized_markets.append(normalized)
                        self._market_cache[normalized["ticker"]] = normalized

            self._cache_timestamp = datetime.now()

            logger.info(f"[polymarket] Fetched {len(normalized_markets)} markets")
            return normalized_markets[:limit]

        except httpx.HTTPError as e:
            logger.error(f"Polymarket API error: {e}")
            return []

    async def get_market(self, ticker: str) -> Dict:
        """
        Get single market by ID/slug.

        Args:
            ticker: Market ID or slug

        Returns:
            Normalized market dict
        """
        if not self._connected:
            await self.connect()

        # Check cache first
        if ticker in self._market_cache:
            return self._market_cache[ticker]

        try:
            # Try by condition_id first, then by slug
            response = await self._http_client.get(f"/markets/{ticker}")

            if response.status_code == 404:
                # Try slug endpoint
                response = await self._http_client.get(f"/markets/slug/{ticker}")

            response.raise_for_status()
            market = response.json()

            normalized = self._normalize_market(market)
            if normalized:
                self._market_cache[normalized["ticker"]] = normalized

            return normalized or {}

        except httpx.HTTPError as e:
            logger.error(f"Polymarket get_market error: {e}")
            return {}

    async def get_orderbook(self, ticker: str) -> Dict:
        """
        Get orderbook for a market.

        Note: Requires CLOB API for full orderbook depth.

        Args:
            ticker: Market ticker (condition_id)

        Returns:
            Orderbook dict with bids and asks
        """
        if not self._connected:
            await self.connect()

        try:
            # The CLOB orderbook endpoint
            clob_url = f"https://clob.polymarket.com/book"
            params = {"token_id": ticker}

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(clob_url, params=params)
                response.raise_for_status()

                data = response.json()

                return {
                    "yes": [
                        {"price": int(float(b["price"]) * 100), "size": int(float(b["size"]))}
                        for b in data.get("bids", [])
                    ],
                    "no": [
                        {"price": int(float(a["price"]) * 100), "size": int(float(a["size"]))}
                        for a in data.get("asks", [])
                    ],
                }

        except httpx.HTTPError as e:
            logger.error(f"Polymarket orderbook error: {e}")
            return {"yes": [], "no": []}

    def _normalize_market(
        self,
        market: Dict[str, Any],
        event: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Normalize Polymarket market data to Kalshi format.

        Converts Polymarket's decimal prices (0-1) to cents (0-100).

        Args:
            market: Raw Polymarket market data
            event: Parent event data (optional)

        Returns:
            Normalized market dict or None if invalid
        """
        if not market:
            return None

        try:
            # Extract prices from outcomePrices array
            outcome_prices = market.get("outcomePrices", "[]")
            if isinstance(outcome_prices, str):
                import json
                try:
                    outcome_prices = json.loads(outcome_prices)
                except json.JSONDecodeError:
                    outcome_prices = []

            # Polymarket prices are decimal 0-1, convert to cents
            yes_price = 0
            no_price = 0
            if len(outcome_prices) >= 1:
                yes_price = int(float(outcome_prices[0]) * 100)
            if len(outcome_prices) >= 2:
                no_price = int(float(outcome_prices[1]) * 100)

            # Get volume (use 24h volume if available)
            volume = market.get("volume24hr", 0) or market.get("volume", 0)
            if isinstance(volume, str):
                try:
                    volume = int(float(volume))
                except ValueError:
                    volume = 0

            # Parse close time
            close_time = market.get("endDate") or market.get("end_date_iso")
            if close_time and isinstance(close_time, str):
                try:
                    close_time = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                except ValueError:
                    close_time = None

            # Build normalized market dict
            return {
                "ticker": market.get("condition_id") or market.get("id") or "",
                "title": market.get("question") or market.get("title", ""),
                "description": market.get("description", ""),
                "yes_bid": yes_price,
                "yes_ask": yes_price,  # Polymarket gives mid price
                "no_bid": no_price,
                "no_ask": no_price,
                "last_price": yes_price,
                "volume": volume,
                "volume_24h": volume,
                "open_interest": market.get("openInterest", 0),
                "close_time": close_time,
                "expiration_time": close_time,
                "status": "open" if market.get("active", True) and not market.get("closed", False) else "closed",
                "event_ticker": event.get("id", "") if event else market.get("eventSlug", ""),
                "series_ticker": "",
                "outcomes": market.get("outcomes", '["Yes", "No"]'),
                "platform": "polymarket",
                # Polymarket-specific fields
                "polymarket_slug": market.get("slug", ""),
                "polymarket_tokens": market.get("clobTokenIds", []),
            }

        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"Failed to normalize Polymarket market: {e}")
            return None

    def _is_cache_valid(self) -> bool:
        """Check if market cache is still valid."""
        if not self._cache_timestamp or not self._market_cache:
            return False

        elapsed = (datetime.now() - self._cache_timestamp).total_seconds()
        return elapsed < self.cache_ttl

    # =========================================================================
    # Cross-Platform Matching Methods
    # =========================================================================

    def find_kalshi_matches(
        self,
        polymarket_markets: List[Dict],
        kalshi_markets: List[Dict],
    ) -> List[MatchedMarketPair]:
        """
        Find Kalshi matches for Polymarket markets.

        Args:
            polymarket_markets: List of normalized Polymarket markets
            kalshi_markets: List of normalized Kalshi markets

        Returns:
            List of MatchedMarketPair objects for matched markets
        """
        matches = []

        for poly_market in polymarket_markets:
            match = self.matcher.find_best_match(poly_market, kalshi_markets)
            if match:
                matches.append(match)

        # Sort by match score
        matches.sort(key=lambda x: x.match_score.total_score if x.match_score else 0, reverse=True)

        return matches

    def get_arbitrage_candidates(
        self,
        matches: List[MatchedMarketPair],
        min_price_diff_cents: int = 5,
    ) -> List[MatchedMarketPair]:
        """
        Filter matches to find arbitrage candidates.

        Args:
            matches: List of matched market pairs
            min_price_diff_cents: Minimum price difference to flag

        Returns:
            List of pairs with price differences >= threshold
        """
        candidates = []

        for match in matches:
            if not match.kalshi_market:
                continue

            # Calculate price difference
            poly_price = match.polymarket_market.get("yes_bid", 0)
            kalshi_price = match.kalshi_market.get("yes_bid", 0)

            price_diff = abs(kalshi_price - poly_price)

            if price_diff >= min_price_diff_cents:
                match.price_diff_cents = kalshi_price - poly_price
                match.is_arbitrage_candidate = True
                candidates.append(match)

        # Sort by absolute price difference
        candidates.sort(key=lambda x: abs(x.price_diff_cents), reverse=True)

        return candidates

    # =========================================================================
    # Trading Methods (NOT SUPPORTED - Read-Only Client)
    # =========================================================================

    async def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        order_type: str = "limit",
    ) -> Dict:
        """
        NOT SUPPORTED - Polymarket client is read-only.

        Raises:
            NotImplementedError: Always - trading not supported
        """
        raise NotImplementedError(
            "Polymarket client is read-only. Trading should be executed on Kalshi."
        )

    async def cancel_order(self, order_id: str) -> bool:
        """
        NOT SUPPORTED - Polymarket client is read-only.

        Raises:
            NotImplementedError: Always - trading not supported
        """
        raise NotImplementedError(
            "Polymarket client is read-only. Trading should be executed on Kalshi."
        )

    async def get_positions(self) -> List[Dict]:
        """
        NOT SUPPORTED - Polymarket client is read-only.

        Returns empty list as we don't hold positions on Polymarket.
        """
        return []

    async def get_balance(self) -> Dict[str, float]:
        """
        NOT SUPPORTED - Polymarket client is read-only.

        Returns zero balance as we don't trade on Polymarket.
        """
        return {
            "balance": 0.0,
            "available": 0.0,
            "portfolio_value": 0.0,
        }
