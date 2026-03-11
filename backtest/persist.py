"""
Backtest Result Persistence — Push backtest/arena results to Supabase.

Maps BacktestResult and StrategyScore to the deepstack_backtest_results table,
enabling hybrid graduation (backtest confidence + paper trading data).

Usage:
    from backtest.persist import persist_backtest_result, persist_arena_results

    # Single strategy backtest
    await persist_backtest_result(result, gate="KALSHI")

    # Full arena tournament
    await persist_arena_results(tournament_result, gate="KALSHI")
"""

import logging
import os
from typing import Optional

import httpx

from backtest.runner import BacktestResult

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
TABLE = "deepstack_backtest_results"

# Gate -> strategy mapping (mirrors dashboard graduation route)
GATE_STRATEGIES = {
    "KALSHI": {
        "calibration_edge", "high_probability_bonds", "momentum", "mean_reversion",
        "combinatorial_arbitrage", "cross_platform_arbitrage", "weather_aggregation",
        "news_sentiment_fade", "correlated_event_arbitrage", "domain_specialization",
        "crypto_intraday", "bear_macro", "settlement_betting",
    },
    "STOCKS": {"stock_momentum", "crisis_alpha"},
    "FUTURES": {"futures_trend"},
    "OPTIONS": {"options_income", "options_directional"},
}


def _gate_for_strategy(strategy_name: str) -> str:
    """Resolve which gate a strategy belongs to."""
    for gate, strategies in GATE_STRATEGIES.items():
        if strategy_name in strategies:
            return gate
    return "KALSHI"  # Default for unknown strategies


def _headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def persist_backtest_result(
    result: BacktestResult,
    gate: Optional[str] = None,
    run_id: Optional[str] = None,
    time_window: Optional[str] = None,
    composite_score: float = 0.0,
) -> bool:
    """Persist a single BacktestResult to Supabase.

    Args:
        result: Completed backtest result.
        gate: Gate label (auto-detected from strategy if not provided).
        run_id: Optional tournament/run ID for grouping.
        time_window: Human-readable time range of the data.
        composite_score: Arena composite score (0-100). Pass 0 for standalone runs.

    Returns:
        True if persisted successfully.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.warning("Supabase not configured — skipping backtest persist")
        return False

    resolved_gate = gate or _gate_for_strategy(result.strategy_name)

    # Cap profit_factor for JSON serialization (inf -> 10.0)
    pf = result.profit_factor
    if pf == float("inf") or pf > 10.0:
        pf = 10.0

    row = {
        "strategy": result.strategy_name,
        "gate": resolved_gate,
        "total_trades": result.total_trades,
        "win_rate": round(result.win_rate, 4),
        "max_drawdown_pct": round(result.max_drawdown_pct, 4),
        "sharpe_ratio": round(result.sharpe_ratio, 4),
        "profit_factor": round(pf, 4),
        "avg_pnl_cents": round(result.avg_pnl_per_trade_cents, 2),
        "total_pnl_cents": result.total_pnl_cents,
        "composite_score": round(composite_score, 2),
        "data_source": result.data_source,
        "time_window": time_window,
        "run_id": run_id,
        "timesteps": result.total_timesteps,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
            resp = await client.post(url, json=row, headers=_headers())
            if resp.status_code in (200, 201):
                logger.info(
                    f"Persisted backtest: {result.strategy_name} "
                    f"({resolved_gate}) score={composite_score:.1f}"
                )
                return True
            logger.error(
                f"Supabase insert failed ({resp.status_code}): {resp.text}"
            )
            return False
    except Exception as e:
        logger.error(f"Backtest persist error: {e}")
        return False


async def persist_arena_results(
    tournament_result: "TournamentResult",
    gate: Optional[str] = None,
) -> int:
    """Persist all ranked strategy scores from an arena tournament.

    Args:
        tournament_result: Completed tournament with rankings.
        gate: Gate label. If None, auto-detects per strategy.

    Returns:
        Number of rows successfully persisted.
    """
    from arena.models import TournamentResult  # noqa: F811

    count = 0
    for score in tournament_result.rankings:
        resolved_gate = gate or _gate_for_strategy(score.strategy_name)

        # Build a minimal BacktestResult-like payload
        pf = score.profit_factor
        if pf == float("inf") or pf > 10.0:
            pf = 10.0

        row = {
            "strategy": score.strategy_name,
            "gate": resolved_gate,
            "total_trades": score.total_trades,
            "win_rate": round(score.win_rate, 4),
            "max_drawdown_pct": round(score.max_drawdown_pct, 4),
            "sharpe_ratio": round(score.sharpe_ratio, 4),
            "profit_factor": round(pf, 4),
            "avg_pnl_cents": round(score.avg_pnl_cents, 2),
            "total_pnl_cents": score.total_pnl_cents,
            "composite_score": round(score.composite_score, 2),
            "data_source": tournament_result.data_source,
            "run_id": tournament_result.tournament_id,
            "timesteps": 0,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
                resp = await client.post(url, json=row, headers=_headers())
                if resp.status_code in (200, 201):
                    count += 1
                else:
                    logger.error(
                        f"Failed to persist {score.strategy_name}: "
                        f"{resp.status_code} {resp.text}"
                    )
        except Exception as e:
            logger.error(f"Persist error for {score.strategy_name}: {e}")

    logger.info(
        f"Persisted {count}/{len(tournament_result.rankings)} arena results "
        f"(run={tournament_result.tournament_id})"
    )
    return count
