"""
Crypto Price Feed

Real-time BTC/ETH/SOL prices from CoinGecko (free tier, 30 req/min).
Used by CryptoIntradayStrategy for fair value calculations and
external momentum signals.

No API key required for basic tier. Uses existing httpx dependency.
"""

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# CoinGecko symbol mapping: our names -> CoinGecko IDs
SYMBOL_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


class CryptoPriceFeed:
    """
    Real-time crypto price feed via CoinGecko free API.

    Features:
    - Batch fetches all symbols in a single API call
    - 15-second in-memory cache to respect rate limits (30 req/min)
    - Graceful fallback: returns empty dict on API failure
    - No API key required

    Usage:
        feed = CryptoPriceFeed()
        prices = await feed.get_prices(["BTC", "ETH", "SOL"])
        # {"BTC": 95234.50, "ETH": 3412.10, "SOL": 198.75}
    """

    def __init__(self, cache_ttl_seconds: int = 15):
        self._cache: Dict[str, Any] = {}
        self._cache_time: float = 0
        self._cache_ttl = cache_ttl_seconds
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def _cache_valid(self) -> bool:
        return (time.time() - self._cache_time) < self._cache_ttl and bool(self._cache)

    async def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch current USD prices for given crypto symbols.

        Args:
            symbols: List of symbols like ["BTC", "ETH", "SOL"]

        Returns:
            Dict mapping symbol to USD price, e.g. {"BTC": 95000.0}
            Empty dict on API failure.
        """
        if self._cache_valid():
            return {s: self._cache.get(s, 0.0) for s in symbols if s in self._cache}

        gecko_ids = [SYMBOL_MAP[s] for s in symbols if s in SYMBOL_MAP]
        if not gecko_ids:
            return {}

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{COINGECKO_BASE}/simple/price",
                params={
                    "ids": ",".join(gecko_ids),
                    "vs_currencies": "usd",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Reverse map: gecko ID -> our symbol
            reverse_map = {v: k for k, v in SYMBOL_MAP.items()}
            result = {}
            for gecko_id, price_data in data.items():
                symbol = reverse_map.get(gecko_id)
                if symbol and "usd" in price_data:
                    result[symbol] = float(price_data["usd"])

            # Update cache
            self._cache = result
            self._cache_time = time.time()

            logger.debug(f"CoinGecko prices: {result}")
            return {s: result.get(s, 0.0) for s in symbols if s in result}

        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.warning(f"CoinGecko API error: {e}")
            # Return stale cache if available
            if self._cache:
                return {s: self._cache.get(s, 0.0) for s in symbols if s in self._cache}
            return {}

    async def get_price_with_change(self, symbol: str) -> Dict[str, float]:
        """
        Get price with 1h and 24h change percentages.

        Args:
            symbol: Crypto symbol like "BTC"

        Returns:
            Dict with keys: price, change_1h, change_24h
            Empty dict on failure.
        """
        gecko_id = SYMBOL_MAP.get(symbol)
        if not gecko_id:
            return {}

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{COINGECKO_BASE}/simple/price",
                params={
                    "ids": gecko_id,
                    "vs_currencies": "usd",
                    "include_1hr_change": "true",
                    "include_24hr_change": "true",
                },
            )
            resp.raise_for_status()
            data = resp.json().get(gecko_id, {})

            return {
                "price": float(data.get("usd", 0)),
                "change_1h": float(data.get("usd_1h_change", 0)),
                "change_24h": float(data.get("usd_24h_change", 0)),
            }

        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.warning(f"CoinGecko price+change error for {symbol}: {e}")
            return {}

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
