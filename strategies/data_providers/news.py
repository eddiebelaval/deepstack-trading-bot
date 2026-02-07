"""
News Data Provider

Fetches and parses RSS feeds from major news sources.
Uses stdlib xml.etree.ElementTree — no new dependencies needed.

Feeds:
- NYT (Top Stories)
- BBC News (World)
- Reuters (Top News)
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)


RSS_FEEDS: Dict[str, str] = {
    "nyt": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "bbc": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "reuters": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best",
}


@dataclass
class NewsEvent:
    """
    A parsed news article from RSS.

    Attributes:
        title: Article headline
        source: Feed name (e.g., "nyt", "bbc")
        published: Publication datetime
        url: Article link
        keywords: Extracted keywords for market matching
        relevance_score: How relevant to prediction markets (0-1)
    """

    title: str
    source: str
    published: Optional[datetime] = None
    url: str = ""
    keywords: List[str] = field(default_factory=list)
    relevance_score: float = 0.0

    def matches_market(self, market_title: str, threshold: float = 0.3) -> bool:
        """Check if this news event is relevant to a market."""
        if not self.keywords:
            return False

        market_words = set(re.findall(r"[a-z]+", market_title.lower()))
        overlap = len(set(self.keywords) & market_words)

        if len(self.keywords) == 0:
            return False

        score = overlap / len(self.keywords)
        return score >= threshold


# Common stop words to filter from keyword extraction
_STOP_WORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "under",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than", "too",
    "very", "just", "about", "also", "then", "it", "its", "that", "this",
    "these", "those", "he", "she", "they", "we", "you", "who", "which",
    "what", "when", "where", "how", "why", "says", "said", "new", "over",
}


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from text."""
    words = re.findall(r"[a-z]+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 2]


class NewsDataProvider:
    """
    Async RSS news feed aggregator.

    Fetches from configured feeds, deduplicates by URL, caches for 5 minutes.
    """

    CACHE_TTL_SECONDS = 300  # 5 minutes

    def __init__(self, feeds: Optional[Dict[str, str]] = None):
        self._feeds = feeds or RSS_FEEDS
        self._cache: Optional[Tuple[float, List[NewsEvent]]] = None
        self._seen_urls: Set[str] = set()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "KalshiTradingBot/1.0"},
            )
        return self._client

    async def get_recent_news(self, max_age_hours: int = 4) -> List[NewsEvent]:
        """
        Fetch recent news articles from all feeds.

        Args:
            max_age_hours: Only return articles published within this window

        Returns:
            List of NewsEvent objects, sorted by recency
        """
        # Check cache
        if self._cache:
            cached_time, cached_events = self._cache
            if time.time() - cached_time < self.CACHE_TTL_SECONDS:
                return cached_events

        events: List[NewsEvent] = []

        for source, url in self._feeds.items():
            try:
                feed_events = await self._fetch_feed(source, url)
                events.extend(feed_events)
            except Exception as e:
                logger.debug(f"Failed to fetch {source} feed: {e}")

        # Dedup by URL
        unique_events: List[NewsEvent] = []
        for event in events:
            if event.url and event.url not in self._seen_urls:
                self._seen_urls.add(event.url)
                unique_events.append(event)
            elif not event.url:
                unique_events.append(event)

        # Filter by age
        cutoff = datetime.now()
        filtered = []
        for event in unique_events:
            if event.published:
                age_hours = (cutoff - event.published).total_seconds() / 3600.0
                if age_hours <= max_age_hours:
                    filtered.append(event)
            else:
                filtered.append(event)  # Keep if no publish date

        # Sort by recency
        filtered.sort(
            key=lambda e: e.published or datetime.min,
            reverse=True,
        )

        # Trim seen URLs set to prevent memory growth
        if len(self._seen_urls) > 5000:
            self._seen_urls = set(list(self._seen_urls)[-2000:])

        self._cache = (time.time(), filtered)
        return filtered

    async def _fetch_feed(self, source: str, url: str) -> List[NewsEvent]:
        """Fetch and parse a single RSS feed."""
        client = await self._get_client()
        resp = await client.get(url)
        resp.raise_for_status()

        events: List[NewsEvent] = []
        root = ElementTree.fromstring(resp.text)

        # Handle both RSS 2.0 and Atom formats
        items = root.findall(".//item") or root.findall(
            ".//{http://www.w3.org/2005/Atom}entry"
        )

        for item in items:
            title_el = item.find("title") or item.find(
                "{http://www.w3.org/2005/Atom}title"
            )
            link_el = item.find("link") or item.find(
                "{http://www.w3.org/2005/Atom}link"
            )
            pub_el = item.find("pubDate") or item.find(
                "{http://www.w3.org/2005/Atom}published"
            )

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            if not title:
                continue

            # Extract link
            link = ""
            if link_el is not None:
                link = link_el.text or link_el.get("href", "")

            # Parse publication date
            published = None
            if pub_el is not None and pub_el.text:
                try:
                    published = parsedate_to_datetime(pub_el.text)
                    # Strip timezone for consistent comparison
                    published = published.replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass

            keywords = _extract_keywords(title)

            events.append(
                NewsEvent(
                    title=title,
                    source=source,
                    published=published,
                    url=link,
                    keywords=keywords,
                )
            )

        return events

    async def find_relevant_news(
        self, market_title: str, max_age_hours: int = 4
    ) -> List[NewsEvent]:
        """Find news articles relevant to a specific market."""
        all_news = await self.get_recent_news(max_age_hours)
        return [
            event for event in all_news
            if event.matches_market(market_title)
        ]

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
