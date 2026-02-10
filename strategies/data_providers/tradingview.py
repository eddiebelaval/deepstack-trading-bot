"""
TradingView Data Provider

Fetches top-performing backtested indicators from Supabase (ds_tv_indicators
and ds_tv_backtests tables). These scores come from the DeepStack TradingView
pipeline which scrapes Pine Script indicators, converts them to Python, and
backtests across multiple tickers.

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars.
Uses existing httpx dependency.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class TradingViewDataProvider:
    """
    Async data provider for TradingView indicator scores stored in Supabase.

    Features:
    - Fetches top indicators ranked by composite_score
    - Per-ticker backtest results for any indicator
    - Signal strength scoring (0-1) based on composite score + consistency
    - 5-minute cache per query
    - Graceful degradation when Supabase is unreachable

    Usage:
        tv = TradingViewDataProvider()
        top = await tv.get_top_indicators(min_sharpe=1.0)
        strength = await tv.get_signal_strength("my-indicator")
    """

    def __init__(self, cache_ttl_seconds: int = 300):
        self._supabase_url = os.environ.get("SUPABASE_URL", "")
        self._supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = cache_ttl_seconds
        self._client: Optional[httpx.AsyncClient] = None

        if not self._supabase_url or not self._supabase_key:
            logger.warning(
                "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set. "
                "TradingView data provider will return empty results."
            )

    @property
    def _rest_url(self) -> str:
        return f"{self._supabase_url}/rest/v1"

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self._supabase_key,
            "Authorization": f"Bearer {self._supabase_key}",
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    def _cache_key(self, prefix: str, *args) -> str:
        return f"{prefix}:{':'.join(str(a) for a in args)}"

    def _cache_valid(self, key: str) -> bool:
        entry = self._cache.get(key)
        if not entry:
            return False
        return (time.time() - entry["time"]) < self._cache_ttl

    async def get_top_indicators(
        self,
        min_sharpe: float = 1.0,
        min_trades: int = 5,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch top indicators from ds_tv_indicators ordered by composite_score DESC.

        Args:
            min_sharpe: Minimum average Sharpe ratio across tickers
            min_trades: Minimum trades (unused filter, reserved for future)
            limit: Max indicators to return

        Returns:
            List of indicator dicts with keys: script_name, composite_score,
            avg_sharpe, avg_return_pct, num_tickers_tested, category.
            Empty list on failure.
        """
        if not self._supabase_url or not self._supabase_key:
            return []

        cache_key = self._cache_key("top_indicators", min_sharpe, limit)
        if self._cache_valid(cache_key):
            return self._cache[cache_key]["data"]

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self._rest_url}/ds_tv_indicators",
                headers=self._headers,
                params={
                    "order": "composite_score.desc.nullslast",
                    "limit": limit,
                    "avg_sharpe": f"gte.{min_sharpe}",
                    "num_tickers_tested": "gte.1",
                },
            )
            resp.raise_for_status()
            result = resp.json()

            self._cache[cache_key] = {"data": result, "time": time.time()}
            logger.debug(f"TradingView: fetched {len(result)} top indicators")
            return result

        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.warning(f"TradingView data provider error (top_indicators): {e}")
            cached = self._cache.get(cache_key)
            if cached:
                return cached["data"]
            return []

    async def get_backtests(self, script_name: str) -> List[Dict[str, Any]]:
        """
        Get per-ticker backtest results for an indicator.

        Args:
            script_name: The indicator script name (slug)

        Returns:
            List of backtest dicts with keys: ticker, return_pct, sharpe_ratio,
            max_drawdown_pct, num_trades, win_rate_pct, etc.
            Empty list on failure.
        """
        if not self._supabase_url or not self._supabase_key:
            return []

        cache_key = self._cache_key("backtests", script_name)
        if self._cache_valid(cache_key):
            return self._cache[cache_key]["data"]

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self._rest_url}/ds_tv_backtests",
                headers=self._headers,
                params={
                    "script_name": f"eq.{script_name}",
                },
            )
            resp.raise_for_status()
            result = resp.json()

            self._cache[cache_key] = {"data": result, "time": time.time()}
            logger.debug(f"TradingView: {len(result)} backtests for {script_name}")
            return result

        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.warning(f"TradingView data provider error (backtests for {script_name}): {e}")
            cached = self._cache.get(cache_key)
            if cached:
                return cached["data"]
            return []

    async def get_signal_strength(self, script_name: str) -> float:
        """
        Return 0-1 confidence score based on composite score + consistency across tickers.

        Scoring:
        - Base: composite_score normalized to 0-1 range (assumes 0-100 scale)
        - Consistency bonus: if Sharpe > 0 across all tested tickers, +0.1
        - Consistency penalty: if any ticker has negative return, -0.1

        Args:
            script_name: The indicator script name

        Returns:
            Float 0.0-1.0 representing signal confidence. 0.0 on failure.
        """
        # Get indicator summary
        top = await self.get_top_indicators(min_sharpe=0.0, limit=100)
        indicator = None
        for ind in top:
            if ind.get("script_name") == script_name:
                indicator = ind
                break

        if not indicator:
            return 0.0

        # Base score from composite_score (normalize 0-100 to 0-1)
        composite = indicator.get("composite_score", 0) or 0
        base_score = min(1.0, max(0.0, composite / 100.0))

        # Consistency check from per-ticker backtests
        backtests = await self.get_backtests(script_name)
        if backtests:
            all_positive_sharpe = all(
                (bt.get("sharpe_ratio") or 0) > 0 for bt in backtests
            )
            any_negative_return = any(
                (bt.get("return_pct") or 0) < 0 for bt in backtests
            )

            if all_positive_sharpe:
                base_score = min(1.0, base_score + 0.1)
            if any_negative_return:
                base_score = max(0.0, base_score - 0.1)

        return round(base_score, 3)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
