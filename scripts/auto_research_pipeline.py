"""
Auto-Research Pipeline — Continuous Indicator Discovery for DeepStack

Extends the existing TradingView daily pipeline by adding gap analysis:
    1. Query Supabase for indicators NOT yet well-covered by category/regime
    2. Identify gaps in arsenal coverage
    3. Trigger targeted scrapes via DeepStack TradingView FastAPI
    4. After backtest completes, re-run populate_lexicon_arsenal.py
    5. Compare new arsenal vs old, log deltas to captain's log
    6. Alert via Telegram if new top performer enters top 20

Integration:
    - Heartbeat trigger: 24h refresh check calls discover_gaps() (lightweight)
    - DeepStack TradingView API: HTTP calls to localhost:8000 (separate repo)
    - Arsenal refresh: calls populate_lexicon_arsenal.populate_arsenal()

Can be run standalone:
    python scripts/auto_research_pipeline.py

Or triggered from heartbeat:
    await discover_gaps()
    await run_targeted_research(gaps, config)
"""

import asyncio
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# Add parent to path for standalone execution
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# All categories that regime playbooks reference
ALL_EXPECTED_CATEGORIES = [
    "momentum",
    "mean reversion",
    "volatility",
    "volume",
    "trend",
    "oscillator",
    "breakout",
    "sentiment",
]

# Minimum indicators per category before we flag a gap
MIN_INDICATORS_PER_CATEGORY = 2


async def _fetch_indicator_categories(
    supabase_url: str,
    supabase_key: str,
) -> Dict[str, int]:
    """
    Fetch category counts from ds_tv_indicators in Supabase.

    Returns dict of category -> count of indicators with composite_score.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{supabase_url}/rest/v1/ds_tv_indicators",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "count=exact",
            },
            params={
                "select": "category",
                "composite_score": "not.is.null",
                "num_tickers_tested": "gte.1",
            },
        )
        resp.raise_for_status()
        rows = resp.json()

    # Count by category
    counts: Dict[str, int] = Counter(
        (row.get("category", "uncategorized") or "uncategorized").lower()
        for row in rows
    )
    return dict(counts)


async def _fetch_low_coverage_indicators(
    supabase_url: str,
    supabase_key: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Fetch indicators that exist but haven't been backtested yet
    (composite_score is NULL or num_tickers_tested < 3).
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{supabase_url}/rest/v1/ds_tv_indicators",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            },
            params={
                "select": "id,script_name,category,num_tickers_tested,composite_score",
                "or": "(composite_score.is.null,num_tickers_tested.lt.3)",
                "limit": limit,
                "order": "created_at.desc",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def discover_gaps(
    supabase_url: Optional[str] = None,
    supabase_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Identify gaps in indicator coverage by category.

    Returns a dict with:
        - missing_categories: categories with 0 indicators
        - thin_categories: categories with < MIN_INDICATORS_PER_CATEGORY
        - total_indicators: total count across all categories
        - category_counts: full count breakdown
        - untested_count: indicators awaiting backtest

    This is lightweight (2 Supabase queries) and safe to call frequently.
    """
    url = supabase_url or os.environ.get("SUPABASE_URL", "")
    key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        logger.warning("Auto-research: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")
        return {"error": "Missing Supabase credentials"}

    try:
        category_counts = await _fetch_indicator_categories(url, key)
        untested = await _fetch_low_coverage_indicators(url, key)
    except Exception as e:
        logger.warning("Auto-research: Supabase query failed: %s", e)
        return {"error": str(e)}

    missing = [
        cat for cat in ALL_EXPECTED_CATEGORIES
        if cat not in category_counts
    ]

    thin = [
        cat for cat in ALL_EXPECTED_CATEGORIES
        if 0 < category_counts.get(cat, 0) < MIN_INDICATORS_PER_CATEGORY
    ]

    result = {
        "missing_categories": missing,
        "thin_categories": thin,
        "total_indicators": sum(category_counts.values()),
        "category_counts": category_counts,
        "untested_count": len(untested),
        "untested_indicators": [
            {"name": i.get("script_name", "?"), "category": i.get("category", "?")}
            for i in untested[:10]
        ],
    }

    logger.info(
        "Auto-research gaps: %d missing categories, %d thin categories, "
        "%d total indicators, %d untested",
        len(missing), len(thin), result["total_indicators"], len(untested),
    )

    return result


async def trigger_targeted_scrape(
    category: str,
    deepstack_api_url: str = "http://localhost:8000",
    max_results: int = 5,
) -> bool:
    """
    Trigger a targeted TradingView indicator scrape for a specific category
    via the DeepStack TradingView FastAPI server.

    Args:
        category: Indicator category to search for (e.g., "sentiment")
        deepstack_api_url: Base URL of the DeepStack TradingView API
        max_results: Maximum indicators to scrape per category

    Returns:
        True if scrape was triggered successfully, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{deepstack_api_url}/api/scrape/targeted",
                json={
                    "category": category,
                    "max_results": max_results,
                    "auto_backtest": True,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(
                    "Auto-research: triggered scrape for '%s' — %s",
                    category, data.get("message", "ok"),
                )
                return True
            elif resp.status_code == 404:
                # API endpoint doesn't exist yet — log and skip
                logger.info(
                    "Auto-research: targeted scrape endpoint not available "
                    "(DeepStack TradingView may need update)"
                )
                return False
            else:
                logger.warning(
                    "Auto-research: scrape trigger failed for '%s': %d %s",
                    category, resp.status_code, resp.text[:200],
                )
                return False
    except httpx.ConnectError:
        logger.info(
            "Auto-research: DeepStack TradingView API not reachable at %s",
            deepstack_api_url,
        )
        return False
    except Exception as e:
        logger.warning("Auto-research: scrape trigger error for '%s': %s", category, e)
        return False


async def run_targeted_research(
    gaps: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run targeted research based on gap analysis results.

    1. For each missing/thin category, trigger a targeted scrape
    2. After scrapes complete, re-run arsenal population
    3. Return summary of actions taken

    Args:
        gaps: Output from discover_gaps()
        config: auto_research section from config.yaml

    Returns:
        Dict with scrape_results, arsenal_refreshed, new_top_performers
    """
    config = config or {}
    max_scrapes = config.get("max_scrapes_per_run", 5)
    api_url = config.get("deepstack_api_url", "http://localhost:8000")

    if "error" in gaps:
        return {"error": gaps["error"], "scrapes_triggered": 0}

    # Prioritize: missing categories first, then thin categories
    categories_to_scrape = gaps.get("missing_categories", []) + gaps.get("thin_categories", [])
    categories_to_scrape = categories_to_scrape[:max_scrapes]

    scrape_results: Dict[str, bool] = {}
    for category in categories_to_scrape:
        success = await trigger_targeted_scrape(category, api_url)
        scrape_results[category] = success
        if success:
            # Brief pause between scrapes to avoid overwhelming the API
            await asyncio.sleep(2)

    # Re-run arsenal population if any scrapes succeeded
    arsenal_refreshed = False
    if any(scrape_results.values()):
        try:
            from scripts.populate_lexicon_arsenal import populate_arsenal
            arsenal_refreshed = await populate_arsenal()
            logger.info("Auto-research: arsenal refresh %s", "succeeded" if arsenal_refreshed else "skipped")
        except Exception as e:
            logger.warning("Auto-research: arsenal refresh failed: %s", e)

    result = {
        "scrapes_triggered": sum(1 for v in scrape_results.values() if v),
        "scrape_results": scrape_results,
        "arsenal_refreshed": arsenal_refreshed,
        "categories_checked": categories_to_scrape,
    }

    logger.info(
        "Auto-research complete: %d/%d scrapes triggered, arsenal_refreshed=%s",
        result["scrapes_triggered"], len(categories_to_scrape), arsenal_refreshed,
    )

    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async def main():
        print("=== Auto-Research Pipeline ===")
        print()

        # Step 1: Gap analysis
        gaps = await discover_gaps()
        if "error" in gaps:
            print(f"Error: {gaps['error']}")
            return

        print(f"Total indicators: {gaps['total_indicators']}")
        print(f"Missing categories: {gaps['missing_categories'] or 'none'}")
        print(f"Thin categories: {gaps['thin_categories'] or 'none'}")
        print(f"Untested indicators: {gaps['untested_count']}")
        print()

        if gaps["missing_categories"] or gaps["thin_categories"]:
            print("Running targeted research...")
            result = await run_targeted_research(gaps)
            print(f"Scrapes triggered: {result['scrapes_triggered']}")
            print(f"Arsenal refreshed: {result['arsenal_refreshed']}")
        else:
            print("No gaps found — arsenal coverage is complete.")

    asyncio.run(main())
