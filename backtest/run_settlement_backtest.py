#!/usr/bin/env python3
"""Settlement Betting Backtest — fetch real Kalshi candles and validate the edge.

Authenticates with Kalshi, pulls hourly candlestick data for KXBTC + KXETH
markets, converts to snapshots, and runs the settlement_betting strategy
through BacktestRunner with the corrected Kelly fraction.

Usage:
    python -m backtest.run_settlement_backtest
    python -m backtest.run_settlement_backtest --days 14 --output results.json
    python -m backtest.run_settlement_backtest --series KXBTC --verbose

Decision gate after backtest:
    win_rate > 25% AND profit_factor > 1.2 AND sharpe > 0.5
    → re-enable settlement_betting in config.yaml
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from kalshi_trader.config import load_config
from kalshi_trader.kalshi_client import AuthenticatedKalshiClient as KalshiClient
from backtest.runner import BacktestRunner
from strategies import load_strategy

logger = logging.getLogger(__name__)

# Decision thresholds from the plan
THRESHOLDS = {
    "min_win_rate": 0.25,
    "min_profit_factor": 1.2,
    "min_sharpe": 0.5,
    "min_trades": 50,
}

SERIES = ["KXBTC", "KXETH"]


async def fetch_candles(
    client: KalshiClient,
    series_list: list[str],
    days: int,
) -> list[dict]:
    """Fetch hourly candles for all open + recently closed markets in given series."""
    now = int(time.time())
    start_ts = now - (days * 86400)
    all_snapshots = []

    for series in series_list:
        # Get markets (open + closed to include recently settled)
        for status in ["open", "closed"]:
            try:
                markets = await client.get_markets(series_ticker=series, status=status, limit=100)
            except Exception as e:
                logger.warning(f"Failed to get {status} markets for {series}: {e}")
                continue

            logger.info(f"{series} ({status}): {len(markets)} markets found")

            for market in markets:
                ticker = market.get("ticker")
                if not ticker:
                    continue

                try:
                    candles = await client.get_candlesticks(
                        ticker=ticker,
                        series_ticker=series,
                        period_interval=60,  # hourly
                        start_ts=start_ts,
                        end_ts=now,
                    )
                except Exception as e:
                    logger.debug(f"Candles failed for {ticker}: {e}")
                    continue

                if not candles:
                    continue

                # Convert each candle to a snapshot
                for candle in candles:
                    candle["ticker"] = ticker
                    snap = BacktestRunner._candle_to_snapshot(candle)
                    if snap:
                        all_snapshots.append(snap)

                logger.debug(f"  {ticker}: {len(candles)} candles")

    all_snapshots.sort(key=lambda s: s["_timestamp"])
    logger.info(f"Total snapshots: {len(all_snapshots)} across {len(series_list)} series")
    return all_snapshots


def evaluate_result(result) -> dict:
    """Check result against decision thresholds."""
    checks = {
        "win_rate": (result.win_rate, THRESHOLDS["min_win_rate"]),
        "profit_factor": (result.profit_factor, THRESHOLDS["min_profit_factor"]),
        "sharpe_ratio": (result.sharpe_ratio, THRESHOLDS["min_sharpe"]),
        "trade_count": (result.total_trades, THRESHOLDS["min_trades"]),
    }

    passed = all(actual >= threshold for actual, threshold in checks.values())

    return {
        "decision": "ENABLE" if passed else "KEEP DISABLED",
        "checks": {
            k: {"actual": round(actual, 4), "threshold": threshold, "passed": actual >= threshold}
            for k, (actual, threshold) in checks.items()
        },
        "passed": passed,
    }


async def main(args):
    config = load_config()
    client = KalshiClient(config)

    series = args.series if args.series else SERIES

    print(f"Fetching {args.days} days of hourly candles for {', '.join(series)}...")
    print()

    await client.connect()
    try:
        snapshots = await fetch_candles(client, series, args.days)
    finally:
        await client.close()

    if not snapshots:
        print("ERROR: No candlestick data retrieved. Check API credentials and market availability.")
        sys.exit(1)

    print(f"Loaded {len(snapshots)} snapshots. Running backtest...")
    print()

    # Load strategy with production config
    strategy = load_strategy("settlement_betting", {})

    runner = BacktestRunner(
        strategy=strategy,
        initial_balance_cents=15_200,  # Current balance ~$152
        max_positions=5,
        contracts_per_trade=1,
    )

    result = await runner.run(
        snapshots,
        data_source=f"Kalshi API ({args.days}d, {', '.join(series)})",
    )

    # Print report
    print(result.summary())

    # Evaluate against thresholds
    evaluation = evaluate_result(result)
    print()
    print("=" * 60)
    print(f"  DECISION: {evaluation['decision']}")
    print("=" * 60)
    for name, check in evaluation["checks"].items():
        icon = "PASS" if check["passed"] else "FAIL"
        print(f"  [{icon}] {name}: {check['actual']} (need >= {check['threshold']})")
    print("=" * 60)

    # Save results if requested
    if args.output:
        output_data = {
            "strategy": result.strategy_name,
            "data_source": result.data_source,
            "days": args.days,
            "series": series,
            "total_snapshots": len(snapshots),
            "total_trades": result.total_trades,
            "win_rate": round(result.win_rate, 4),
            "total_pnl_cents": result.total_pnl_cents,
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "profit_factor": round(result.profit_factor, 4) if result.profit_factor != float("inf") else "inf",
            "max_drawdown_pct": round(result.max_drawdown_pct, 4),
            "initial_balance_cents": result.initial_balance_cents,
            "final_balance_cents": result.final_balance_cents,
            "evaluation": evaluation,
        }
        Path(args.output).write_text(json.dumps(output_data, indent=2))
        print(f"\nResults saved to {args.output}")


def cli():
    parser = argparse.ArgumentParser(
        description="Backtest settlement_betting strategy against real Kalshi data",
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Days of historical data to fetch (default: 30)",
    )
    parser.add_argument(
        "--series", nargs="+", default=None,
        help=f"Series to backtest (default: {' '.join(SERIES)})",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Save results as JSON to this path",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show debug logs",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
