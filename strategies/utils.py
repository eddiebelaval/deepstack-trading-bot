"""
Shared Strategy Utilities

Common helper functions used across multiple trading strategies.
Extracted to avoid duplication and ensure consistent behavior.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def get_mid_price(market: Dict[str, Any]) -> int:
    """
    Calculate mid-price from market bid/ask data.

    Falls back to last_price if bid/ask unavailable,
    then defaults to 50 (maximum uncertainty).

    Args:
        market: Market data dict with yes_bid/yes_ask/last_price keys

    Returns:
        Mid-price in cents (1-99)
    """
    yes_bid = market.get("yes_bid", 0)
    yes_ask = market.get("yes_ask", 0)

    if yes_bid and yes_ask:
        return (yes_bid + yes_ask) // 2

    return market.get("last_price", 50)


def score_spread(
    yes_bid: int,
    yes_ask: int,
    no_bid: int,
    no_ask: int,
    max_score: float = 30.0,
) -> float:
    """
    Score bid-ask spread quality. Tighter spreads = better liquidity.

    Args:
        yes_bid: YES bid price in cents
        yes_ask: YES ask price in cents
        no_bid: NO bid price in cents
        no_ask: NO ask price in cents
        max_score: Maximum score to return (default 30.0)

    Returns:
        Score from 0 to max_score (higher = tighter spread)
    """
    yes_spread = (yes_ask - yes_bid) if (yes_ask and yes_bid) else 10
    no_spread = (no_ask - no_bid) if (no_ask and no_bid) else 10

    avg_spread = (yes_spread + no_spread) / 2

    if avg_spread <= 1:
        return max_score
    elif avg_spread >= 10:
        return 0.0
    else:
        return max_score * (1 - (avg_spread - 1) / 9)


def score_volume(volume: int, target: int = 1000, max_score: float = 30.0) -> float:
    """
    Score market volume. Higher volume = more reliable signals.

    Args:
        volume: Market trading volume
        target: Volume level that earns max score
        max_score: Maximum score to return

    Returns:
        Score from 0 to max_score
    """
    if target <= 0:
        return 0.0
    return min(volume / target, 1.0) * max_score


def hours_until_close(market: Dict[str, Any]) -> Optional[float]:
    """
    Calculate hours until market closes/settles.

    Args:
        market: Market data dict with close_time or expiration_time

    Returns:
        Hours until close, or None if unknown
    """
    close_time_str = market.get("close_time") or market.get("expiration_time")
    if not close_time_str:
        return None

    try:
        if isinstance(close_time_str, str):
            close_time = datetime.fromisoformat(
                close_time_str.replace("Z", "+00:00")
            )
        elif isinstance(close_time_str, datetime):
            close_time = close_time_str
        else:
            return None

        now = datetime.now(close_time.tzinfo)
        delta = (close_time - now).total_seconds()
        return delta / 3600.0 if delta > 0 else 0.0
    except (ValueError, TypeError):
        return None


def is_market_tradeable(
    market: Dict[str, Any],
    min_volume: int = 100,
    require_prices: bool = True,
) -> bool:
    """
    Check if a market meets basic tradeability criteria.

    Args:
        market: Market data dict
        min_volume: Minimum volume threshold
        require_prices: Whether to require valid bid/ask prices

    Returns:
        True if market is tradeable
    """
    if market.get("status") not in ("open", "active"):
        return False

    volume = market.get("volume", 0) or market.get("volume_24h", 0)
    if volume < min_volume:
        return False

    if require_prices:
        yes_ask = market.get("yes_ask", 0)
        if not yes_ask or yes_ask <= 0 or yes_ask >= 100:
            return False

    return True


def clamp_score(score: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    """Clamp a score to [min_val, max_val]."""
    return max(min_val, min(max_val, score))
