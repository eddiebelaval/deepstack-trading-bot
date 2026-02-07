"""
Market Data Cache with TTL

Provides in-memory caching for market data to reduce API calls.
Uses TTL (Time-To-Live) to ensure data freshness.

Design:
- LRU eviction when cache reaches max size
- Per-key TTL for fine-grained expiration
- Thread-safe for async operations
- Metrics for cache monitoring
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class CacheEntry(Generic[T]):
    """Single cache entry with value and expiration."""
    value: T
    expires_at: float
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at

    @property
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.created_at


@dataclass
class CacheStats:
    """Statistics for cache monitoring."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class MarketCache(Generic[T]):
    """
    TTL-based cache for market data.

    Reduces API calls by caching market data with configurable TTL.
    Uses LRU eviction when cache reaches maximum size.

    Example:
        >>> cache = MarketCache[Dict](default_ttl=30.0, max_size=1000)
        >>>
        >>> # Basic usage
        >>> cache.set("INXD-25JAN26-4500", market_data)
        >>> data = cache.get("INXD-25JAN26-4500")
        >>>
        >>> # With fetch function
        >>> async def fetch_market(ticker):
        ...     return await api.get_market(ticker)
        >>>
        >>> data = await cache.get_or_fetch(
        ...     "INXD-25JAN26-4500",
        ...     fetch_market,
        ... )
    """

    def __init__(
        self,
        default_ttl: float = 30.0,
        max_size: int = 1000,
        name: str = "market_cache",
    ):
        """
        Initialize market cache.

        Args:
            default_ttl: Default time-to-live in seconds
            max_size: Maximum number of entries
            name: Cache name for logging
        """
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.name = name

        self._cache: Dict[str, CacheEntry[T]] = {}
        self._access_order: list[str] = []  # For LRU eviction
        self._stats = CacheStats()
        self._lock = asyncio.Lock()

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    @property
    def size(self) -> int:
        """Current number of entries."""
        return len(self._cache)

    def get(self, key: str) -> Optional[T]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        entry = self._cache.get(key)

        if entry is None:
            self._stats.misses += 1
            return None

        if entry.is_expired:
            self._stats.expirations += 1
            self._stats.misses += 1
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            return None

        self._stats.hits += 1

        # Update LRU order
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        return entry.value

    def set(
        self,
        key: str,
        value: T,
        ttl: Optional[float] = None,
    ) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: TTL in seconds (uses default if not specified)
        """
        ttl = ttl if ttl is not None else self.default_ttl
        expires_at = time.time() + ttl

        # Evict if at capacity
        while len(self._cache) >= self.max_size:
            self._evict_lru()

        self._cache[key] = CacheEntry(value=value, expires_at=expires_at)

        # Update LRU order
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

    async def get_or_fetch(
        self,
        key: str,
        fetch_func: Callable[[], Any],
        ttl: Optional[float] = None,
    ) -> T:
        """
        Get from cache or fetch if missing/expired.

        Thread-safe: uses lock to prevent thundering herd.

        Args:
            key: Cache key
            fetch_func: Async function to fetch value
            ttl: TTL for fetched value

        Returns:
            Cached or freshly fetched value
        """
        # Quick check without lock
        cached = self.get(key)
        if cached is not None:
            return cached

        # Fetch with lock to prevent duplicate fetches
        async with self._lock:
            # Double-check after acquiring lock
            cached = self.get(key)
            if cached is not None:
                return cached

            # Fetch fresh data
            logger.debug(f"Cache miss for '{key}', fetching...")
            value = await fetch_func()
            self.set(key, value, ttl)
            return value

    def invalidate(self, key: str) -> bool:
        """
        Remove entry from cache.

        Args:
            key: Cache key

        Returns:
            True if entry was removed
        """
        if key in self._cache:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            return True
        return False

    def invalidate_prefix(self, prefix: str) -> int:
        """
        Remove all entries with given prefix.

        Args:
            prefix: Key prefix to match

        Returns:
            Number of entries removed
        """
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for key in keys_to_remove:
            self.invalidate(key)
        return len(keys_to_remove)

    def clear(self) -> None:
        """Clear all entries from cache."""
        count = len(self._cache)
        self._cache.clear()
        self._access_order.clear()
        logger.info(f"Cache '{self.name}' cleared ({count} entries)")

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries removed
        """
        now = time.time()
        expired_keys = [
            k for k, v in self._cache.items()
            if v.expires_at < now
        ]

        for key in expired_keys:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            self._stats.expirations += 1

        if expired_keys:
            logger.debug(
                f"Cache '{self.name}' cleaned up {len(expired_keys)} expired entries"
            )

        return len(expired_keys)

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._access_order:
            return

        lru_key = self._access_order.pop(0)
        if lru_key in self._cache:
            del self._cache[lru_key]
            self._stats.evictions += 1
            logger.debug(f"Cache '{self.name}' evicted LRU key: {lru_key}")

    def get_info(self) -> Dict[str, Any]:
        """Get cache information for monitoring."""
        return {
            "name": self.name,
            "size": self.size,
            "max_size": self.max_size,
            "default_ttl": self.default_ttl,
            "hit_rate": self.stats.hit_rate,
            "hits": self.stats.hits,
            "misses": self.stats.misses,
            "evictions": self.stats.evictions,
            "expirations": self.stats.expirations,
        }


# Singleton instance for market data
_market_cache: Optional[MarketCache[Dict[str, Any]]] = None


def get_market_cache(
    default_ttl: float = 30.0,
    max_size: int = 1000,
) -> MarketCache[Dict[str, Any]]:
    """
    Get or create the global market cache instance.

    Args:
        default_ttl: Default TTL in seconds
        max_size: Maximum cache size

    Returns:
        MarketCache singleton instance
    """
    global _market_cache
    if _market_cache is None:
        _market_cache = MarketCache(
            default_ttl=default_ttl,
            max_size=max_size,
            name="global_market_cache",
        )
    return _market_cache
