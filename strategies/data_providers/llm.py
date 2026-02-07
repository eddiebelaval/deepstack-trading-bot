"""
LLM Provider

Async Claude Sonnet wrapper for strategy-level analysis.
Used by NewsSentimentFade to assess whether market reactions are overblown.

Graceful degradation: returns neutral signal if no ANTHROPIC_API_KEY.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


@dataclass
class OverreactionAnalysis:
    """
    Result of LLM overreaction assessment.

    Attributes:
        is_overreaction: Whether the market move is assessed as overreaction
        confidence: Confidence in the assessment (0-1)
        reasoning: Short explanation
        raw_response: Full LLM response text
    """

    is_overreaction: bool = False
    confidence: float = 0.5
    reasoning: str = ""
    raw_response: str = ""


class LLMProvider:
    """
    Async Claude API wrapper with rate limiting and caching.

    Rate limited to 10 calls/minute. Caches results for 10 minutes.
    """

    MAX_CALLS_PER_MINUTE = 10
    CACHE_TTL_SECONDS = 600  # 10 minutes

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-5-20250929"):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._model = model
        self._client: Optional[httpx.AsyncClient] = None
        self._call_timestamps: list = []
        self._cache: Dict[str, Tuple[float, OverreactionAnalysis]] = {}

    @property
    def is_available(self) -> bool:
        """Check if LLM provider has a valid API key."""
        return bool(self._api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        return self._client

    def _check_rate_limit(self) -> bool:
        """Check if we can make another call within rate limit."""
        now = time.time()
        # Remove timestamps older than 1 minute
        self._call_timestamps = [
            ts for ts in self._call_timestamps if now - ts < 60
        ]
        return len(self._call_timestamps) < self.MAX_CALLS_PER_MINUTE

    async def analyze_overreaction(
        self,
        market_title: str,
        price_before: int,
        price_after: int,
        news_headline: str,
        volume_surge: float,
    ) -> OverreactionAnalysis:
        """
        Assess whether a market price spike is an overreaction to news.

        Args:
            market_title: The prediction market title
            price_before: Price before the spike (cents)
            price_after: Price after the spike (cents)
            news_headline: The news headline that may have caused the spike
            volume_surge: Volume multiplier during spike

        Returns:
            OverreactionAnalysis with assessment
        """
        if not self.is_available:
            logger.debug("LLM provider unavailable (no API key), returning neutral")
            return OverreactionAnalysis(
                is_overreaction=False,
                confidence=0.0,
                reasoning="LLM unavailable — no API key configured",
            )

        # Check cache
        cache_key = f"{market_title}:{price_before}:{price_after}:{news_headline}"
        if cache_key in self._cache:
            cached_time, cached_result = self._cache[cache_key]
            if time.time() - cached_time < self.CACHE_TTL_SECONDS:
                return cached_result

        # Check rate limit
        if not self._check_rate_limit():
            logger.debug("LLM rate limit reached, returning neutral")
            return OverreactionAnalysis(
                is_overreaction=False,
                confidence=0.0,
                reasoning="Rate limit reached",
            )

        try:
            result = await self._call_claude(
                market_title, price_before, price_after, news_headline, volume_surge
            )
            self._cache[cache_key] = (time.time(), result)
            return result
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            return OverreactionAnalysis(
                is_overreaction=False,
                confidence=0.0,
                reasoning=f"API error: {str(e)[:100]}",
            )

    async def _call_claude(
        self,
        market_title: str,
        price_before: int,
        price_after: int,
        news_headline: str,
        volume_surge: float,
    ) -> OverreactionAnalysis:
        """Make the actual Claude API call."""
        client = await self._get_client()

        price_change = price_after - price_before
        direction = "up" if price_change > 0 else "down"

        prompt = (
            f"You are analyzing a prediction market price movement.\n\n"
            f"Market: {market_title}\n"
            f"Price moved {abs(price_change)} cents {direction} "
            f"(from {price_before}c to {price_after}c)\n"
            f"News headline: {news_headline}\n"
            f"Volume surge: {volume_surge:.1f}x normal\n\n"
            f"Is this price movement likely an overreaction to the news?\n"
            f"Consider: Does the news materially change the probability of this "
            f"market's outcome, or is the market overweighting short-term sentiment?\n\n"
            f"Respond with exactly one line in this format:\n"
            f"OVERREACTION|<confidence 0.0-1.0>|<brief reason>\n"
            f"or\n"
            f"JUSTIFIED|<confidence 0.0-1.0>|<brief reason>"
        )

        self._call_timestamps.append(time.time())

        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            json={
                "model": self._model,
                "max_tokens": 150,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()

        data = resp.json()
        text = data.get("content", [{}])[0].get("text", "").strip()

        return self._parse_response(text)

    def _parse_response(self, text: str) -> OverreactionAnalysis:
        """Parse Claude's structured response."""
        line = text.split("\n")[0].strip()
        parts = line.split("|")

        if len(parts) >= 3:
            verdict = parts[0].strip().upper()
            try:
                confidence = float(parts[1].strip())
                confidence = max(0.0, min(1.0, confidence))
            except ValueError:
                confidence = 0.5
            reasoning = parts[2].strip()

            return OverreactionAnalysis(
                is_overreaction=(verdict == "OVERREACTION"),
                confidence=confidence,
                reasoning=reasoning,
                raw_response=text,
            )

        # Fallback: try to detect from text
        is_over = "overreaction" in text.lower()
        return OverreactionAnalysis(
            is_overreaction=is_over,
            confidence=0.4,
            reasoning=text[:200],
            raw_response=text,
        )

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
