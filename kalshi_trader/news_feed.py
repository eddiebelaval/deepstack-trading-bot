"""
News Feed — Lightweight News Sentiment Signal Source

Fetches headlines from RSS feeds (default) or NewsAPI.org (if NEWS_API_KEY set),
scores them with keyword-based sentiment analysis, and produces signals
compatible with the ForwardSignalBridge.

No LLM required. V1 uses simple keyword matching against curated word lists
for bearish, bullish, and geopolitical categories. Confidence is derived from
keyword density and headline volume.

Default source: RSS feeds from Reuters, MarketWatch, CNBC.
Optional source: NewsAPI.org free tier (100 req/day, 1-hour delay on free plan).
"""

import asyncio
import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

BEARISH_KEYWORDS = frozenset({
    "war", "crash", "recession", "tariff", "tariffs", "sanctions", "default",
    "crisis", "collapse", "layoffs", "downgrade", "downturn", "sell-off",
    "selloff", "bankruptcy", "inflation", "hawkish", "shutdown", "plunge",
    "tumble", "slump", "contraction", "deficit", "debt ceiling",
})

BULLISH_KEYWORDS = frozenset({
    "rally", "surge", "growth", "deal", "breakthrough", "recovery", "upgrade",
    "stimulus", "peace", "ceasefire", "boom", "dovish", "rate cut", "hiring",
    "expansion", "rebound", "optimism", "record high", "all-time high",
    "bull", "bullish",
})

GEOPOLITICAL_KEYWORDS = frozenset({
    "iran", "war", "military", "strike", "oil", "sanctions", "defense",
    "conflict", "nuclear", "missile", "troops", "invasion", "nato",
    "china", "taiwan", "russia", "ukraine", "north korea", "houthi",
    "red sea", "terrorist", "terrorism", "coup", "embargo",
})

# ---------------------------------------------------------------------------
# RSS feed sources (no API key needed)
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/topNews",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",      # Top News
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",       # Markets
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://feeds.marketwatch.com/marketwatch/marketpulse/",
]


class SentimentDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class NewsSignal:
    """Output of the news feed sentiment analysis."""
    direction: str                  # "bullish" / "bearish" / "neutral"
    confidence: float               # 0.0 - 1.0
    keywords_matched: List[str]
    headline_count: int
    geopolitical: bool = False      # True if geopolitical keywords detected
    geo_keywords: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "rss"             # "rss" or "newsapi"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "confidence": self.confidence,
            "keywords_matched": self.keywords_matched,
            "headline_count": self.headline_count,
            "geopolitical": self.geopolitical,
            "geo_keywords": self.geo_keywords,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }


class NewsFeed:
    """
    Lightweight news aggregator that fetches headlines and scores sentiment.

    Usage:
        feed = NewsFeed(poll_interval_minutes=5)
        signal = await feed.get_latest_signal()
        geo = await feed.get_geopolitical_signal()
    """

    def __init__(
        self,
        poll_interval_minutes: int = 5,
        newsapi_key: Optional[str] = None,
    ):
        self.poll_interval = poll_interval_minutes * 60  # seconds
        self._newsapi_key = newsapi_key or os.environ.get("NEWS_API_KEY")
        self._last_poll: float = 0.0
        self._cached_headlines: List[str] = []
        self._cached_signal: Optional[NewsSignal] = None
        self._http_session = None

        source = "NewsAPI.org" if self._newsapi_key else "RSS feeds"
        logger.info(
            "NewsFeed initialized | source=%s, poll_interval=%d min",
            source, poll_interval_minutes,
        )

    async def _get_http_session(self):
        """Lazy-init aiohttp session."""
        if self._http_session is None or self._http_session.closed:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=15)
            self._http_session = aiohttp.ClientSession(timeout=timeout)
        return self._http_session

    async def close(self) -> None:
        """Clean up HTTP session."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_latest_signal(self) -> Optional[NewsSignal]:
        """Get the latest news sentiment signal, polling if stale."""
        now = time.monotonic()
        if now - self._last_poll >= self.poll_interval or not self._cached_signal:
            headlines = await self._fetch_headlines()
            if headlines:
                self._cached_headlines = headlines
                self._cached_signal = self._score_headlines(headlines)
                self._last_poll = now
                logger.info(
                    "News feed: %s (conf=%.2f, %d headlines, %d keywords) [%s]",
                    self._cached_signal.direction,
                    self._cached_signal.confidence,
                    self._cached_signal.headline_count,
                    len(self._cached_signal.keywords_matched),
                    self._cached_signal.source,
                )
        return self._cached_signal

    async def get_geopolitical_signal(self) -> Optional[NewsSignal]:
        """Check specifically for geopolitical risk headlines.

        Returns a signal focused on geopolitical keywords only,
        or None if no geopolitical headlines detected.
        """
        # Ensure we have fresh headlines
        await self.get_latest_signal()

        if not self._cached_headlines:
            return None

        geo_matches = []
        matched_headlines = 0

        for headline in self._cached_headlines:
            lower = headline.lower()
            hits = [kw for kw in GEOPOLITICAL_KEYWORDS if kw in lower]
            if hits:
                geo_matches.extend(hits)
                matched_headlines += 1

        if not geo_matches:
            return None

        # Geopolitical news is inherently bearish for equities / risk assets
        unique_keywords = list(set(geo_matches))
        density = matched_headlines / max(len(self._cached_headlines), 1)
        keyword_breadth = len(unique_keywords) / max(len(GEOPOLITICAL_KEYWORDS), 1)
        confidence = min(1.0, (density * 0.6 + keyword_breadth * 0.4) * 3.0)

        # Only emit if meaningful
        if confidence < 0.15:
            return None

        return NewsSignal(
            direction=SentimentDirection.BEARISH.value,
            confidence=round(confidence, 3),
            keywords_matched=unique_keywords,
            headline_count=matched_headlines,
            geopolitical=True,
            geo_keywords=unique_keywords,
            source=self._cached_signal.source if self._cached_signal else "rss",
        )

    # ------------------------------------------------------------------
    # Headline fetching
    # ------------------------------------------------------------------

    async def _fetch_headlines(self) -> List[str]:
        """Fetch headlines from configured source."""
        if self._newsapi_key:
            return await self._fetch_newsapi()
        return await self._fetch_rss()

    async def _fetch_rss(self) -> List[str]:
        """Fetch headlines from RSS feeds (no API key required)."""
        headlines: List[str] = []
        session = await self._get_http_session()

        tasks = [self._fetch_single_rss(session, url) for url in RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.debug("RSS feed error: %s", result)
                continue
            headlines.extend(result)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for h in headlines:
            normalized = h.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(h.strip())

        return unique

    async def _fetch_single_rss(self, session, url: str) -> List[str]:
        """Fetch headlines from a single RSS feed URL."""
        headlines = []
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()

            root = ET.fromstring(text)
            # Standard RSS 2.0: channel/item/title
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    headlines.append(title_el.text.strip())
            # Atom feeds: entry/title
            if not headlines:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                    title_el = entry.find("atom:title", ns)
                    if title_el is None:
                        title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                    if title_el is not None and title_el.text:
                        headlines.append(title_el.text.strip())
        except Exception as exc:
            logger.debug("RSS parse error for %s: %s", url, exc)

        return headlines

    async def _fetch_newsapi(self) -> List[str]:
        """Fetch headlines from NewsAPI.org (requires API key)."""
        headlines = []
        session = await self._get_http_session()

        url = "https://newsapi.org/v2/top-headlines"
        params = {
            "category": "business",
            "language": "en",
            "pageSize": 100,
            "apiKey": self._newsapi_key,
        }

        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("NewsAPI returned %d — falling back to RSS", resp.status)
                    return await self._fetch_rss()
                data = await resp.json()

            for article in data.get("articles", []):
                title = article.get("title", "")
                if title and title != "[Removed]":
                    headlines.append(title.strip())
        except Exception as exc:
            logger.warning("NewsAPI error: %s — falling back to RSS", exc)
            return await self._fetch_rss()

        return headlines

    # ------------------------------------------------------------------
    # Sentiment scoring
    # ------------------------------------------------------------------

    def _score_headlines(self, headlines: List[str]) -> NewsSignal:
        """Score a batch of headlines using keyword matching."""
        bearish_hits: List[str] = []
        bullish_hits: List[str] = []
        geo_hits: List[str] = []

        for headline in headlines:
            lower = headline.lower()
            for kw in BEARISH_KEYWORDS:
                if kw in lower:
                    bearish_hits.append(kw)
            for kw in BULLISH_KEYWORDS:
                if kw in lower:
                    bullish_hits.append(kw)
            for kw in GEOPOLITICAL_KEYWORDS:
                if kw in lower:
                    geo_hits.append(kw)

        bearish_score = len(bearish_hits)
        bullish_score = len(bullish_hits)
        total_hits = bearish_score + bullish_score

        # Direction
        if bearish_score > bullish_score:
            direction = SentimentDirection.BEARISH
        elif bullish_score > bearish_score:
            direction = SentimentDirection.BULLISH
        else:
            direction = SentimentDirection.NEUTRAL

        # Confidence: based on keyword density and margin between bull/bear
        if total_hits == 0:
            confidence = 0.0
        else:
            margin = abs(bearish_score - bullish_score) / max(total_hits, 1)
            density = total_hits / max(len(headlines), 1)
            # Blend margin (how lopsided) with density (how saturated)
            confidence = min(1.0, (margin * 0.7 + density * 0.3) * 2.0)

        all_keywords = list(set(bearish_hits + bullish_hits))
        unique_geo = list(set(geo_hits))

        source = "newsapi" if self._newsapi_key else "rss"

        return NewsSignal(
            direction=direction.value,
            confidence=round(confidence, 3),
            keywords_matched=all_keywords,
            headline_count=len(headlines),
            geopolitical=bool(geo_hits),
            geo_keywords=unique_geo,
            source=source,
        )
