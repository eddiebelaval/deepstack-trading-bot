"""
FRED Data Provider

Federal Reserve Economic Data for macro trading signals.
Provides economic indicator data (Fed rate, CPI, GDP, unemployment)
and bear/bull market regime detection.

Requires FRED_API_KEY env var (free from https://fred.stlouisfed.org/docs/api/api_key.html).
Uses existing httpx dependency.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"

# Key FRED series for macro trading
SERIES = {
    "FEDFUNDS": "Federal Funds Effective Rate",
    "CPIAUCSL": "Consumer Price Index (All Urban, Seasonally Adjusted)",
    "GDP": "Real Gross Domestic Product",
    "UNRATE": "Unemployment Rate",
    "T10Y2Y": "10-Year minus 2-Year Treasury Spread",
}


class FredDataProvider:
    """
    Economic indicator data from FRED (Federal Reserve Economic Data).

    Features:
    - Fetches latest observations for any FRED series
    - 5-minute cache per series (economic data updates infrequently)
    - Bull/bear regime detection via yield curve + unemployment
    - Graceful degradation when API key is missing

    Usage:
        fred = FredDataProvider()
        data = await fred.get_latest("FEDFUNDS", periods=12)
        regime = await fred.get_regime_signals()
    """

    def __init__(self, cache_ttl_seconds: int = 300):
        self._api_key = os.environ.get("FRED_API_KEY", "")
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = cache_ttl_seconds
        self._client: Optional[httpx.AsyncClient] = None

        if not self._api_key:
            logger.warning(
                "FRED_API_KEY not set. Bear macro strategy will use fallback estimates."
            )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    def _cache_key(self, series_id: str, periods: int) -> str:
        return f"{series_id}:{periods}"

    def _cache_valid(self, key: str) -> bool:
        entry = self._cache.get(key)
        if not entry:
            return False
        return (time.time() - entry["time"]) < self._cache_ttl

    async def get_latest(
        self, series_id: str, periods: int = 12
    ) -> List[Dict[str, Any]]:
        """
        Get most recent observations for a FRED series.

        Args:
            series_id: FRED series ID (e.g., "FEDFUNDS", "CPIAUCSL")
            periods: Number of recent observations to fetch

        Returns:
            List of dicts with keys: date, value
            Most recent first. Empty list on failure.
        """
        if not self._api_key:
            return []

        cache_key = self._cache_key(series_id, periods)
        if self._cache_valid(cache_key):
            return self._cache[cache_key]["data"]

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{FRED_BASE}/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": periods,
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("observations", [])

            result = []
            for obs in raw:
                val = obs.get("value", ".")
                if val == ".":
                    continue
                result.append({
                    "date": obs.get("date", ""),
                    "value": float(val),
                })

            self._cache[cache_key] = {"data": result, "time": time.time()}
            logger.debug(f"FRED {series_id}: {len(result)} observations")
            return result

        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.warning(f"FRED API error for {series_id}: {e}")
            # Return stale cache if available
            cached = self._cache.get(cache_key)
            if cached:
                return cached["data"]
            return []

    async def get_regime_signals(self) -> Dict[str, float]:
        """
        Detect bull/bear market regime from economic indicators.

        Signals:
        - yield_curve: T10Y2Y spread (negative = inverted = bearish)
        - unemployment_trend: Change in unemployment rate (positive = bearish)
        - fed_rate_trend: Change in fed funds rate (positive = tightening)
        - regime_score: -1.0 (strong bear) to +1.0 (strong bull)

        Returns:
            Dict of signal names to values. All zeros if API unavailable.
        """
        defaults = {
            "yield_curve": 0.0,
            "unemployment_trend": 0.0,
            "fed_rate_trend": 0.0,
            "regime_score": 0.0,
        }

        if not self._api_key:
            return defaults

        # Fetch all indicators
        t10y2y = await self.get_latest("T10Y2Y", periods=3)
        unrate = await self.get_latest("UNRATE", periods=3)
        fedfunds = await self.get_latest("FEDFUNDS", periods=3)

        signals = dict(defaults)

        # Yield curve: current spread value
        if t10y2y:
            signals["yield_curve"] = t10y2y[0]["value"]

        # Unemployment trend: recent change
        if len(unrate) >= 2:
            signals["unemployment_trend"] = unrate[0]["value"] - unrate[1]["value"]

        # Fed rate trend: recent change
        if len(fedfunds) >= 2:
            signals["fed_rate_trend"] = fedfunds[0]["value"] - fedfunds[1]["value"]

        # Composite regime score: -1 (bear) to +1 (bull)
        score = 0.0
        # Inverted yield curve is bearish
        if signals["yield_curve"] < 0:
            score -= 0.4
        elif signals["yield_curve"] > 0.5:
            score += 0.2

        # Rising unemployment is bearish
        if signals["unemployment_trend"] > 0.1:
            score -= 0.3
        elif signals["unemployment_trend"] < -0.1:
            score += 0.2

        # Rising fed rate is tightening (bearish for equities)
        if signals["fed_rate_trend"] > 0:
            score -= 0.3
        elif signals["fed_rate_trend"] < 0:
            score += 0.2

        signals["regime_score"] = max(-1.0, min(1.0, score))

        logger.info(
            f"Regime signals: yield_curve={signals['yield_curve']:.2f}, "
            f"unemployment_trend={signals['unemployment_trend']:.2f}, "
            f"regime_score={signals['regime_score']:.2f}"
        )

        return signals

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
