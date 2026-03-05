"""
Populate Lexicon Arsenal — Fetch top indicators from Supabase and write arsenal files.

Connects to the DeepStack TradingView pipeline (ds_tv_indicators table in Supabase)
and generates markdown files for Dae's strategy lexicon:
  - tv-top-performers.md: Top 20 indicators ranked by composite score
  - tv-regime-map.md: Indicator categories mapped to market regimes

Uses httpx + PostgREST (same pattern as strategies/data_providers/tradingview.py).

Can be run standalone:
    python scripts/populate_lexicon_arsenal.py

Or called from heartbeat:
    await populate_arsenal()
"""

import asyncio
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx

# Add parent to path so we can import consciousness when run standalone
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# Arsenal output paths
_ARSENAL_DIR = _PROJECT_ROOT / "kalshi_trader" / "mind" / "lexicon" / "arsenal"
_TOP_PERFORMERS_PATH = _ARSENAL_DIR / "tv-top-performers.md"
_REGIME_MAP_PATH = _ARSENAL_DIR / "tv-regime-map.md"

# Category -> regime mapping (based on indicator behavior characteristics)
_CATEGORY_REGIME_MAP: Dict[str, Dict[str, Any]] = {
    "momentum": {
        "best": ["TRENDING_UP", "TRENDING_DOWN"],
        "worst": ["MEAN_REVERTING"],
        "notes": "Trend-following indicators, best with directional movement",
    },
    "mean reversion": {
        "best": ["MEAN_REVERTING"],
        "worst": ["TRENDING_UP", "TRENDING_DOWN"],
        "notes": "Range-bound oscillators, buy oversold / sell overbought",
    },
    "volatility": {
        "best": ["HIGH_VOL_CHOPPY"],
        "worst": ["LOW_VOL_CALM"],
        "notes": "Vol expansion strategies, ATR-based entries",
    },
    "volume": {
        "best": ["All regimes"],
        "worst": [],
        "notes": "Confirmation indicators, regime-agnostic",
    },
    "trend": {
        "best": ["TRENDING_UP", "TRENDING_DOWN"],
        "worst": ["HIGH_VOL_CHOPPY"],
        "notes": "Directional strength (ADX, moving averages)",
    },
    "oscillator": {
        "best": ["MEAN_REVERTING", "LOW_VOL_CALM"],
        "worst": ["TRENDING_UP", "TRENDING_DOWN"],
        "notes": "Overbought/oversold signals (RSI, Stochastic)",
    },
    "breakout": {
        "best": ["TRENDING_UP", "HIGH_VOL_CHOPPY"],
        "worst": ["LOW_VOL_CALM"],
        "notes": "Range break detection, works at regime transitions",
    },
    "sentiment": {
        "best": ["HIGH_VOL_CHOPPY", "MEAN_REVERTING"],
        "worst": [],
        "notes": "Crowd positioning indicators, contrarian signals",
    },
}


async def _fetch_top_indicators(
    supabase_url: str,
    supabase_key: str,
    min_sharpe: float = 1.0,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Fetch top indicators from ds_tv_indicators via PostgREST."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{supabase_url}/rest/v1/ds_tv_indicators",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            },
            params={
                "order": "composite_score.desc.nullslast",
                "limit": limit,
                "avg_sharpe": f"gte.{min_sharpe}",
                "num_tickers_tested": "gte.1",
            },
        )
        resp.raise_for_status()
        return resp.json()


def _generate_top_performers_md(indicators: List[Dict[str, Any]]) -> str:
    """Generate tv-top-performers.md content from indicator data."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# TradingView Arsenal — Top Performers",
        "",
        f"Auto-populated from DeepStack TradingView pipeline (Supabase `ds_tv_indicators`).",
        f"Last refresh: {now}",
        "",
        "## Top 20 Indicators by Composite Score",
        "",
        "| Rank | Name | Composite | Avg Sharpe | Avg Return % | Tickers | Category |",
        "|------|------|-----------|------------|--------------|---------|----------|",
    ]

    for i, ind in enumerate(indicators, 1):
        name = ind.get("script_name", "unknown")
        composite = ind.get("composite_score", 0) or 0
        sharpe = ind.get("avg_sharpe", 0) or 0
        ret = ind.get("avg_return_pct", 0) or 0
        tickers = ind.get("num_tickers_tested", 0) or 0
        category = ind.get("category", "uncategorized") or "uncategorized"
        lines.append(
            f"| {i} | {name} | {composite:.1f} | {sharpe:.2f} | {ret:.1f}% | {tickers} | {category} |"
        )

    # Category summary
    categories = Counter(
        (ind.get("category", "uncategorized") or "uncategorized")
        for ind in indicators
    )
    lines.extend([
        "",
        "## Category Summary",
        "",
        "| Category | Count | Avg Composite |",
        "|----------|-------|---------------|",
    ])

    for cat, count in categories.most_common():
        cat_indicators = [
            ind for ind in indicators
            if (ind.get("category", "uncategorized") or "uncategorized") == cat
        ]
        avg_comp = sum(
            (ind.get("composite_score", 0) or 0) for ind in cat_indicators
        ) / max(len(cat_indicators), 1)
        lines.append(f"| {cat} | {count} | {avg_comp:.1f} |")

    lines.append("")
    return "\n".join(lines)


def _generate_regime_map_md(indicators: List[Dict[str, Any]]) -> str:
    """Generate tv-regime-map.md content from indicator data and category mapping."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# TradingView Arsenal — Regime Map",
        "",
        f"Maps indicator categories to market regimes. Auto-populated from DeepStack TradingView pipeline.",
        f"Last refresh: {now}",
        "",
        "## Category-Regime Mapping",
        "",
        "| Category | Best Regime | Worst Regime | Notes |",
        "|----------|-------------|--------------|-------|",
    ]

    # Get unique categories from actual data
    seen_categories = set(
        (ind.get("category", "uncategorized") or "uncategorized").lower()
        for ind in indicators
    )

    for cat_key, mapping in _CATEGORY_REGIME_MAP.items():
        best = ", ".join(mapping["best"]) if mapping["best"] else "—"
        worst = ", ".join(mapping["worst"]) if mapping["worst"] else "—"
        notes = mapping["notes"]
        # Mark if we have active indicators in this category
        active = " *" if cat_key in seen_categories else ""
        lines.append(f"| {cat_key}{active} | {best} | {worst} | {notes} |")

    # List indicators by regime
    lines.extend([
        "",
        "\\* = has active top-performing indicators",
        "",
        "## Active Indicators by Regime",
        "",
    ])

    # Group indicators by their best regime
    regime_indicators: Dict[str, List[str]] = {}
    for ind in indicators:
        cat = (ind.get("category", "uncategorized") or "uncategorized").lower()
        mapping = _CATEGORY_REGIME_MAP.get(cat, {"best": ["All regimes"]})
        for regime in mapping["best"]:
            regime_indicators.setdefault(regime, []).append(
                ind.get("script_name", "unknown")
            )

    for regime in ["TRENDING_UP", "TRENDING_DOWN", "MEAN_REVERTING", "HIGH_VOL_CHOPPY", "LOW_VOL_CALM"]:
        inds = regime_indicators.get(regime, [])
        lines.append(f"**{regime}:** {', '.join(inds[:5]) if inds else 'none from top 20'}")

    lines.append("")
    return "\n".join(lines)


async def populate_arsenal() -> bool:
    """
    Main entry point: fetch indicators from Supabase and write arsenal files.

    Returns True on success, False on failure.
    """
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        logger.warning("Arsenal: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set, skipping")
        return False

    try:
        indicators = await _fetch_top_indicators(supabase_url, supabase_key)
        logger.info(f"Arsenal: fetched {len(indicators)} indicators from Supabase")
    except Exception as e:
        logger.warning(f"Arsenal: failed to fetch indicators: {e}")
        return False

    if not indicators:
        logger.info("Arsenal: no indicators meet criteria (Sharpe >= 1.0), keeping existing files")
        return False

    # Ensure arsenal directory exists
    _ARSENAL_DIR.mkdir(parents=True, exist_ok=True)

    # Write files
    try:
        top_performers_content = _generate_top_performers_md(indicators)
        _TOP_PERFORMERS_PATH.write_text(top_performers_content, encoding="utf-8")
        logger.info(f"Arsenal: wrote {_TOP_PERFORMERS_PATH}")

        regime_map_content = _generate_regime_map_md(indicators)
        _REGIME_MAP_PATH.write_text(regime_map_content, encoding="utf-8")
        logger.info(f"Arsenal: wrote {_REGIME_MAP_PATH}")
    except Exception as e:
        logger.warning(f"Arsenal: failed to write files: {e}")
        return False

    # Invalidate consciousness cache for arsenal files
    try:
        from kalshi_trader import consciousness
        consciousness.invalidate_cache("lexicon/arsenal/tv-top-performers.md")
        consciousness.invalidate_cache("lexicon/arsenal/tv-regime-map.md")
        logger.debug("Arsenal: consciousness cache invalidated for arsenal paths")
    except ImportError:
        logger.debug("Arsenal: consciousness module not available for cache invalidation")

    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    success = asyncio.run(populate_arsenal())
    print(f"Arsenal population: {'success' if success else 'failed'}")
    sys.exit(0 if success else 1)
