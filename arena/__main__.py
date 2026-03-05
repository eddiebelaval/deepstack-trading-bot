"""
Arena CLI — Run tournaments from the command line.

Usage:
    python -m arena                                    # Synthetic, defaults
    python -m arena --synthetic 10000 --seed 123       # More data
    python -m arena --csv candles.csv                  # CSV data
    python -m arena --db data.db                       # SQLite
    python -m arena --strategies mean_reversion,market_making  # Subset
    python -m arena --json                             # JSON output
    python -m arena -v                                 # Verbose
    python -m arena --promote                          # Show recommendations
    python -m arena --promote --apply                  # Write to config.yaml
    python -m arena --history                          # Past tournaments
    python -m arena --strategy-report market_making    # One strategy's history

Seas (multi-regime):
    python -m arena --seas                             # All 5 sea conditions
    python -m arena --seas --seas-regime trending_up   # Single sea
    python -m arena --seas --json                      # JSON with regime_scores
    python -m arena --seas --update-fitness            # Show proposed fitness changes
    python -m arena --seas --update-fitness --apply    # Write to trade_journal.db
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arena.config import ArenaConfig
from arena.engine import TournamentEngine

logger = logging.getLogger(__name__)


def _format_leaderboard(result) -> str:
    """Format tournament results as a terminal leaderboard."""
    lines = []
    divider = "=" * 80
    section = "-" * 80

    duration = ""
    if result.started_at and result.finished_at:
        secs = (result.finished_at - result.started_at).total_seconds()
        duration = f" ({secs:.1f}s)"

    lines.append("")
    lines.append(divider)
    lines.append(f"  STRATEGY ARENA — TOURNAMENT RESULTS{duration}")
    lines.append(divider)
    lines.append(f"  Data source:  {result.data_source}")
    lines.append(f"  Windows:      {result.total_windows}")
    lines.append(f"  Strategies:   {result.total_strategies}")
    lines.append("")
    lines.append(section)
    lines.append(
        f"  {'Rank':<6}{'Strategy':<30}{'Score':<8}"
        f"{'WinRate':<9}{'Sharpe':<9}{'PF':<8}"
        f"{'DD%':<8}{'PnL(c)':<10}{'Trades':<7}"
    )
    lines.append(section)

    for score in result.rankings:
        lines.append(
            f"  {score.rank:<6}{score.strategy_name:<30}"
            f"{score.composite_score:<8.1f}"
            f"{score.win_rate:<9.1%}"
            f"{score.sharpe_ratio:<9.2f}"
            f"{score.profit_factor:<8.2f}"
            f"{score.max_drawdown_pct:<8.1%}"
            f"{score.total_pnl_cents:<+10}"
            f"{score.total_trades:<7}"
        )

    lines.append(section)

    # Per-regime leaderboards (seas mode)
    if result.regime_scores:
        lines.append("")
        lines.append(divider)
        lines.append("  PER-REGIME LEADERBOARDS (Top 5 per sea)")
        lines.append(divider)

        for regime, scores in result.regime_scores.items():
            lines.append(f"\n  --- {regime.upper()} ---")
            for score in scores[:5]:
                lines.append(
                    f"    {score.rank:<4}{score.strategy_name:<28}"
                    f"{score.composite_score:<8.1f}"
                    f"{score.total_trades} trades"
                )

    if result.errors:
        lines.append("")
        lines.append("  ERRORS:")
        for name, windows in result.errors.items():
            lines.append(f"    {name}: failed on {len(windows)} window(s)")

    lines.append(divider)
    return "\n".join(lines)


def _format_json(result) -> str:
    """Format tournament results as JSON."""
    output = {
        "tournament_id": result.tournament_id,
        "data_source": result.data_source,
        "total_windows": result.total_windows,
        "total_strategies": result.total_strategies,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "finished_at": result.finished_at.isoformat() if result.finished_at else None,
        "rankings": [
            {
                "rank": s.rank,
                "strategy": s.strategy_name,
                "composite_score": s.composite_score,
                "win_rate": round(s.win_rate, 4),
                "sharpe_ratio": round(s.sharpe_ratio, 4),
                "profit_factor": round(s.profit_factor, 4),
                "max_drawdown_pct": round(s.max_drawdown_pct, 4),
                "total_pnl_cents": s.total_pnl_cents,
                "total_trades": s.total_trades,
                "avg_pnl_cents": round(s.avg_pnl_cents, 2),
            }
            for s in result.rankings
        ],
        "errors": result.errors,
    }

    # Include per-regime scores if present (seas mode)
    if result.regime_scores:
        output["regime_scores"] = {
            regime: [
                {
                    "rank": s.rank,
                    "strategy": s.strategy_name,
                    "composite_score": s.composite_score,
                    "total_trades": s.total_trades,
                }
                for s in scores
            ]
            for regime, scores in result.regime_scores.items()
        }

        # Compute and include fitness matrix
        from arena.scoring import CompositeScorer

        matrix = CompositeScorer.compute_fitness_matrix(result.regime_scores)
        output["fitness_matrix"] = matrix

    return json.dumps(output, indent=2)


def _build_config(args) -> ArenaConfig:
    """Build ArenaConfig from CLI args."""
    config = ArenaConfig()

    # Data source
    if args.csv:
        config.data_source = "csv"
        config.data_path = args.csv
    elif args.db:
        config.data_source = "sqlite"
        config.data_path = args.db
        config.data_query = args.query
    else:
        config.data_source = "synthetic"
        if args.synthetic is not None:
            config.synthetic_timesteps = args.synthetic
        config.synthetic_seed = args.seed

    # Walk-forward params
    if args.is_months:
        config.is_months = args.is_months
    if args.oos_months:
        config.oos_months = args.oos_months

    # Backtest params
    config.initial_balance_cents = args.balance

    # Exclusions
    if args.exclude:
        extra = [s.strip() for s in args.exclude.split(",")]
        config.exclude_strategies.extend(extra)

    # Seas mode
    if hasattr(args, "seas") and args.seas:
        config.seas_mode = True
        config.data_source = "seas"
        if hasattr(args, "seas_regime") and args.seas_regime:
            config.seas_regimes = [
                s.strip() for s in args.seas_regime.split(",")
            ]
        if hasattr(args, "seas_timesteps") and args.seas_timesteps:
            config.seas_timesteps_per_regime = args.seas_timesteps

    if hasattr(args, "update_fitness") and args.update_fitness:
        config.update_fitness = True

    return config


async def _run_tournament(args) -> None:
    """Run a tournament and output results."""
    config = _build_config(args)
    engine = TournamentEngine(config)

    # Strategy subset
    strategy_names = None
    if args.strategies:
        strategy_names = [s.strip() for s in args.strategies.split(",")]

    result = await engine.run_tournament(strategy_names=strategy_names)

    # Output
    if args.json:
        print(_format_json(result))
    else:
        print(_format_leaderboard(result))

    # Promotion recommendations
    if args.promote:
        from arena.promotion import PromotionPipeline

        pipeline = PromotionPipeline(config)
        candidates = pipeline.evaluate(result.rankings)
        diff = pipeline.generate_diff(candidates)
        print(diff)

        if args.apply:
            pipeline.apply(candidates)
            print("\n  Config updated. Backup saved as config.yaml.bak")

    # Fitness update (seas mode only)
    if hasattr(args, "update_fitness") and args.update_fitness and result.regime_scores:
        from arena.fitness import FitnessWriter
        from arena.scoring import CompositeScorer

        matrix = CompositeScorer.compute_fitness_matrix(result.regime_scores)
        writer = FitnessWriter(config.fitness_db_path)

        current = writer.read_current()
        diff_output = writer.generate_diff(current, matrix)
        print(diff_output)

        if args.apply:
            writer.backup_current()
            count = writer.write_fitness(matrix, result.tournament_id)
            print(f"\n  Applied {count} fitness scores to {config.fitness_db_path}")
        else:
            print("\n  (Dry run — add --apply to write changes)")

    # Persistence
    if not args.no_save:
        try:
            from arena.storage import ArenaDB

            db = ArenaDB()
            db.save_tournament(result)
            if result.regime_scores:
                db.save_regime_data(result)
            logger.info(f"Tournament saved: {result.tournament_id}")
        except Exception as e:
            logger.warning(f"Failed to save tournament: {e}")


async def _show_history() -> None:
    """Show past tournament results."""
    from arena.storage import ArenaDB

    db = ArenaDB()
    tournaments = db.list_tournaments()

    if not tournaments:
        print("  No tournament history found.")
        return

    print("\n  TOURNAMENT HISTORY")
    print("  " + "-" * 60)
    for t in tournaments:
        print(
            f"  {t['id'][:8]}  {t['started_at']}  "
            f"{t['data_source']}  {t['strategy_count']} strategies"
        )


async def _show_strategy_report(name: str) -> None:
    """Show historical performance for one strategy."""
    from arena.storage import ArenaDB

    db = ArenaDB()
    history = db.get_strategy_history(name)

    if not history:
        print(f"  No history found for strategy: {name}")
        return

    print(f"\n  STRATEGY REPORT: {name}")
    print("  " + "-" * 60)
    for entry in history:
        print(
            f"  Tournament {entry['tournament_id'][:8]}  "
            f"Rank: {entry['rank']}  Score: {entry['composite_score']:.1f}  "
            f"Trades: {entry['total_trades']}  PnL: {entry['total_pnl_cents']:+}c"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DeepStack Strategy Arena — Walk-Forward Tournament Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Data source
    data = parser.add_argument_group("data source")
    data.add_argument("--synthetic", "-n", type=int, default=None,
                      help="Generate N synthetic timesteps (default: 5000)")
    data.add_argument("--seed", type=int, default=42,
                      help="Random seed for synthetic data (default: 42)")
    data.add_argument("--csv", default=None, help="Path to CSV file")
    data.add_argument("--db", default=None, help="Path to SQLite database")
    data.add_argument("--query", "-q", default=None,
                      help="SQL query for --db mode")

    # Walk-forward params
    wf = parser.add_argument_group("walk-forward")
    wf.add_argument("--is-months", type=int, default=None,
                     help="In-sample window months (default: 6)")
    wf.add_argument("--oos-months", type=int, default=None,
                     help="Out-of-sample window months (default: 1)")

    # Backtest params
    bt = parser.add_argument_group("backtest")
    bt.add_argument("--balance", type=int, default=15_000,
                     help="Initial balance in cents (default: 15000)")

    # Strategy selection
    strat = parser.add_argument_group("strategies")
    strat.add_argument("--strategies", "-s", default=None,
                        help="Comma-separated strategy names (default: all eligible)")
    strat.add_argument("--exclude", default=None,
                        help="Additional strategies to exclude (comma-separated)")

    # Output
    out = parser.add_argument_group("output")
    out.add_argument("--json", action="store_true", help="JSON output")
    out.add_argument("--verbose", "-v", action="store_true", help="Debug logs")
    out.add_argument("--no-save", action="store_true",
                      help="Don't save results to arena_results.db")

    # Promotion
    promo = parser.add_argument_group("promotion")
    promo.add_argument("--promote", action="store_true",
                        help="Show promotion/demotion recommendations")
    promo.add_argument("--apply", action="store_true",
                        help="Apply promotion changes to config.yaml")

    # Seas (multi-regime)
    seas = parser.add_argument_group("seas (multi-regime)")
    seas.add_argument("--seas", action="store_true",
                       help="Run multi-regime seas tournament (all 5 conditions)")
    seas.add_argument("--seas-regime", default=None,
                       help="Comma-separated regime subset (e.g. trending_up,high_vol_choppy)")
    seas.add_argument("--seas-timesteps", type=int, default=None,
                       help="Timesteps per sea (default: 10000)")
    seas.add_argument("--update-fitness", action="store_true",
                       help="Show proposed fitness changes for governance router")

    # History
    hist = parser.add_argument_group("history")
    hist.add_argument("--history", action="store_true",
                       help="Show past tournament results")
    hist.add_argument("--strategy-report", default=None,
                       help="Show history for one strategy")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.history:
        asyncio.run(_show_history())
    elif args.strategy_report:
        asyncio.run(_show_strategy_report(args.strategy_report))
    else:
        asyncio.run(_run_tournament(args))


if __name__ == "__main__":
    main()
