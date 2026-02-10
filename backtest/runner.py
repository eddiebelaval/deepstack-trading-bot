"""
Backtest Runner -- Replay historical market data through any DeepStack strategy.

Simulates trading by stepping through market snapshots chronologically,
calling scan_opportunities() and check_exit() on each timestep, and
tracking simulated P&L, win rate, max drawdown, and Sharpe ratio.

The runner uses the exact same Strategy interface as production, so any
strategy works without modification.

Usage:
    # Synthetic data (immediate test, no real data needed):
    python -m backtest.runner --strategy mean_reversion --synthetic 500

    # CSV candlestick data:
    python -m backtest.runner --strategy mean_reversion --csv candles.csv

    # SQLite (custom query):
    python -m backtest.runner --strategy mean_reversion --db data.db --query "SELECT ..."

    # As a library:
    from backtest.runner import BacktestRunner
    from strategies import load_strategy

    strategy = load_strategy("mean_reversion", {})
    runner = BacktestRunner(strategy)
    snapshots = BacktestRunner.generate_synthetic("INXD-TEST", timesteps=500)
    result = asyncio.run(runner.run(snapshots))
    print(result.summary())
"""

import argparse
import asyncio
import csv
import json
import logging
import math
import random
import sqlite3
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow imports from project root when run as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies import load_strategy, Strategy
from strategies.base import TradingOpportunity, ExitSignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SimulatedTrade:
    """A single simulated trade with entry/exit tracking."""

    ticker: str
    side: str
    entry_price_cents: int
    entry_time: datetime
    contracts: int
    strategy_name: str
    score: float = 0.0
    reasoning: str = ""
    exit_price_cents: Optional[int] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None

    @property
    def pnl_cents(self) -> int:
        """Total P&L in cents. Positive = profit."""
        if self.exit_price_cents is None:
            return 0
        return (self.exit_price_cents - self.entry_price_cents) * self.contracts

    @property
    def is_closed(self) -> bool:
        return self.exit_price_cents is not None

    @property
    def is_winner(self) -> bool:
        return self.pnl_cents > 0


@dataclass
class BacktestResult:
    """Computed metrics from a backtest run."""

    strategy_name: str
    strategy_config: Dict[str, Any]
    data_source: str
    total_timesteps: int

    # Trade counts
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float

    # P&L
    total_pnl_cents: int
    avg_pnl_per_trade_cents: float
    largest_win_cents: int
    largest_loss_cents: int
    avg_winner_cents: float
    avg_loser_cents: float

    # Risk
    max_drawdown_cents: int
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    max_consecutive_wins: int
    max_consecutive_losses: int

    # Equity
    initial_balance_cents: int
    final_balance_cents: int
    equity_curve: List[int]

    # Raw data
    trades: List[SimulatedTrade]

    def summary(self) -> str:
        """Formatted summary report for terminal output."""
        divider = "=" * 60
        section = "-" * 60
        n = max(self.total_trades, 1)
        loss_rate = self.losing_trades / n
        ret = (self.final_balance_cents - self.initial_balance_cents) / max(
            self.initial_balance_cents, 1
        )

        lines = [
            "",
            divider,
            f"  BACKTEST REPORT: {self.strategy_name}",
            divider,
            f"  Data source:       {self.data_source}",
            f"  Timesteps:         {self.total_timesteps:,}",
            f"  Config:            {self.strategy_config}",
            "",
            section,
            "  PERFORMANCE",
            section,
            f"  Total trades:      {self.total_trades}",
            f"  Winners:           {self.winning_trades}  ({self.win_rate:.1%})",
            f"  Losers:            {self.losing_trades}  ({loss_rate:.1%})",
            f"  Breakeven:         {self.breakeven_trades}",
            "",
            f"  Total P&L:         {self.total_pnl_cents:+,}c  (${self.total_pnl_cents / 100:+,.2f})",
            f"  Avg P&L/trade:     {self.avg_pnl_per_trade_cents:+.1f}c",
            f"  Largest win:       {self.largest_win_cents:+,}c",
            f"  Largest loss:      {self.largest_loss_cents:+,}c",
            f"  Avg winner:        {self.avg_winner_cents:+.1f}c",
            f"  Avg loser:         {self.avg_loser_cents:+.1f}c",
            "",
            section,
            "  RISK",
            section,
            f"  Max drawdown:      {self.max_drawdown_cents:,}c  ({self.max_drawdown_pct:.1%})",
            f"  Sharpe ratio:      {self.sharpe_ratio:.2f}",
            f"  Profit factor:     {self.profit_factor:.2f}",
            f"  Max consec. wins:  {self.max_consecutive_wins}",
            f"  Max consec. losses:{self.max_consecutive_losses}",
            "",
            section,
            "  EQUITY",
            section,
            f"  Initial balance:   {self.initial_balance_cents:,}c  (${self.initial_balance_cents / 100:,.2f})",
            f"  Final balance:     {self.final_balance_cents:,}c  (${self.final_balance_cents / 100:,.2f})",
            f"  Return:            {ret:.1%}",
            "",
            divider,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------


class BacktestRunner:
    """
    Replay historical market data through any Strategy.

    Feeds timestamped market snapshots to the strategy's scan_opportunities()
    and check_exit() methods, simulating fills and tracking P&L.

    Fill model: instant fills at snapshot bid/ask prices. Entry fills at
    the ask (buying cost), exit fills at the bid (selling proceeds). The
    bid-ask spread in the data acts as the implicit transaction cost.
    """

    def __init__(
        self,
        strategy: Strategy,
        initial_balance_cents: int = 10_000,
        max_positions: int = 5,
        contracts_per_trade: int = 1,
        commission_cents_per_contract: int = 0,
    ):
        """
        Args:
            strategy: Any instantiated Strategy (from load_strategy or direct).
            initial_balance_cents: Starting simulated cash balance.
            max_positions: Maximum concurrent open positions.
            contracts_per_trade: Fixed contract count per entry.
            commission_cents_per_contract: Per-contract round-trip commission.
        """
        self.strategy = strategy
        self.initial_balance = initial_balance_cents
        self.max_positions = max_positions
        self.contracts_per_trade = contracts_per_trade
        self.commission = commission_cents_per_contract

        # Simulation state (reset on each run)
        self._balance = initial_balance_cents
        self._open_positions: Dict[str, SimulatedTrade] = {}
        self._closed_trades: List[SimulatedTrade] = []
        self._equity_curve: List[int] = []

    # ------------------------------------------------------------------
    # Data loaders
    # ------------------------------------------------------------------

    @staticmethod
    def load_csv(path: str) -> List[Dict]:
        """
        Load market snapshots from a CSV file.

        Auto-detects two column formats:

        1. Snapshot format (bid/ask columns):
           timestamp, ticker, title, yes_bid, yes_ask, no_bid, no_ask,
           volume, status

        2. Candlestick format (OHLCV):
           timestamp, ticker, open, high, low, close, volume
           (title, status, and bid/ask are synthesized from close price)

        Args:
            path: Path to CSV file.

        Returns:
            List of market snapshot dicts sorted by timestamp.
        """
        snapshots = []
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            headers = set(reader.fieldnames or [])
            is_candle = "close" in headers and "yes_bid" not in headers

            for row in reader:
                if is_candle:
                    snap = BacktestRunner._candle_to_snapshot(row)
                else:
                    snap = BacktestRunner._row_to_snapshot(row)
                if snap:
                    snapshots.append(snap)

        snapshots.sort(key=lambda s: s["_timestamp"])
        logger.info(f"Loaded {len(snapshots)} snapshots from CSV: {path}")
        return snapshots

    @staticmethod
    def load_sqlite(
        db_path: str,
        query: Optional[str] = None,
        table: str = "market_snapshots",
    ) -> List[Dict]:
        """
        Load market snapshots from a SQLite database.

        If no query is provided, reads all rows from the given table.
        The result set must return rows with either snapshot or candlestick
        columns (auto-detected).

        Args:
            db_path: Path to SQLite database file.
            query: SQL query (overrides table). Must return snapshot columns.
            table: Table name to SELECT * from (default: market_snapshots).

        Returns:
            List of market snapshot dicts sorted by timestamp.
        """
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            sql = query or f"SELECT * FROM {table} ORDER BY timestamp"
            rows = conn.execute(sql).fetchall()
        finally:
            conn.close()

        snapshots = []
        for row in rows:
            row_dict = dict(row)
            if "close" in row_dict and "yes_bid" not in row_dict:
                snap = BacktestRunner._candle_to_snapshot(row_dict)
            else:
                snap = BacktestRunner._row_to_snapshot(row_dict)
            if snap:
                snapshots.append(snap)

        snapshots.sort(key=lambda s: s["_timestamp"])
        logger.info(f"Loaded {len(snapshots)} snapshots from SQLite: {db_path}")
        return snapshots

    @staticmethod
    def generate_synthetic(
        ticker: str = "BACKTEST-SYNTH",
        title: str = "Synthetic Backtest Market",
        timesteps: int = 500,
        start_price: int = 50,
        volatility: float = 2.0,
        mean_reversion_strength: float = 0.05,
        volume_base: int = 500,
        spread: int = 2,
        interval_minutes: int = 60,
        seed: Optional[int] = None,
    ) -> List[Dict]:
        """
        Generate synthetic market snapshots using an Ornstein-Uhlenbeck
        (mean-reverting) random walk.

        The O-U process is: dX = theta * (mu - X) * dt + sigma * dW
        where theta = mean_reversion_strength, mu = 50c, sigma = volatility.
        This produces price paths that oscillate around 50c -- ideal for
        validating the mean_reversion strategy.

        Args:
            ticker: Market ticker name.
            title: Market title.
            timesteps: Number of time periods to generate.
            start_price: Starting YES price in cents (1-99).
            volatility: Per-step standard deviation in cents.
            mean_reversion_strength: Pull toward 50c (0 = random walk, 1 = snap).
            volume_base: Mean volume per period.
            spread: Bid-ask spread in cents.
            interval_minutes: Minutes between snapshots.
            seed: Random seed for reproducibility.

        Returns:
            List of market snapshot dicts with _timestamp keys.
        """
        if seed is not None:
            random.seed(seed)

        snapshots = []
        price = float(start_price)
        mu = 50.0
        now = datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)
        delta = timedelta(minutes=interval_minutes)

        for _ in range(timesteps):
            # Ornstein-Uhlenbeck step
            drift = mean_reversion_strength * (mu - price)
            noise = random.gauss(0, volatility)
            price = price + drift + noise
            price = max(3.0, min(97.0, price))

            price_int = int(round(price))
            half_spread = max(1, spread // 2)

            yes_bid = max(1, price_int - half_spread)
            yes_ask = min(99, price_int + half_spread)
            no_price = 100 - price_int
            no_bid = max(1, no_price - half_spread)
            no_ask = min(99, no_price + half_spread)

            vol = max(0, int(volume_base + random.gauss(0, volume_base * 0.3)))

            snapshots.append(
                {
                    "_timestamp": now,
                    "ticker": ticker,
                    "title": title,
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "no_bid": no_bid,
                    "no_ask": no_ask,
                    "last_price": price_int,
                    "volume": vol,
                    "volume_24h": vol,
                    "open_interest": vol * 2,
                    "status": "open",
                    "close_time": (now + timedelta(days=7)).isoformat(),
                }
            )
            now += delta

        logger.info(
            f"Generated {len(snapshots)} synthetic snapshots "
            f"(ticker={ticker}, vol={volatility}, mr={mean_reversion_strength})"
        )
        return snapshots

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    async def run(
        self,
        snapshots: List[Dict],
        data_source: str = "unknown",
    ) -> BacktestResult:
        """
        Run the backtest simulation.

        For each timestep (group of snapshots sharing a timestamp):
        1. Check exit conditions on all open positions.
        2. Scan for new entry opportunities.
        3. Fill the top opportunities up to max_positions capacity.

        After all timesteps, any remaining open positions are force-closed
        at the last known bid prices.

        Args:
            snapshots: List of market snapshot dicts. Each must include a
                       '_timestamp' key (datetime). Other keys match what
                       strategies expect: ticker, yes_bid, yes_ask, etc.
            data_source: Label for the report header.

        Returns:
            BacktestResult with all computed metrics and trade list.
        """
        self._reset()

        if not snapshots:
            return self._build_result(data_source, 0)

        grouped = self._group_by_timestamp(snapshots)
        total_timesteps = len(grouped)

        for ts, markets in grouped:
            price_lookup = {m["ticker"]: m for m in markets}

            # 1. Check exits first (mirrors production _manage_positions)
            await self._check_exits(price_lookup, ts)

            # 2. Scan for entries if we have capacity
            if len(self._open_positions) < self.max_positions:
                await self._scan_and_fill(markets, ts)

        # Force-close remaining positions
        if self._open_positions:
            _, last_markets = grouped[-1]
            last_prices = {m["ticker"]: m for m in last_markets}
            self._force_close_all(last_prices, grouped[-1][0])

        return self._build_result(data_source, total_timesteps)

    def _reset(self) -> None:
        """Reset simulation state for a fresh run."""
        self._balance = self.initial_balance
        self._open_positions = {}
        self._closed_trades = []
        self._equity_curve = [self.initial_balance]

    async def _check_exits(
        self,
        price_lookup: Dict[str, Dict],
        current_time: datetime,
    ) -> None:
        """Check exit conditions on all open positions."""
        to_close: List[Tuple[str, int, str, datetime]] = []

        for ticker, trade in self._open_positions.items():
            market = price_lookup.get(ticker)
            if market is None:
                continue

            # Exit price = bid (what we'd sell at)
            if trade.side == "yes":
                current_price = market.get("yes_bid", market.get("last_price", 50))
            else:
                current_price = market.get("no_bid", market.get("last_price", 50))

            position_dict = {
                "ticker": ticker,
                "side": trade.side,
                "entry_price": trade.entry_price_cents,
                "contracts": trade.contracts,
                "entry_time": trade.entry_time,
            }

            signal = await self.strategy.check_exit(
                position=position_dict,
                current_price=current_price,
                market_data=market,
            )

            if signal.should_exit:
                to_close.append((ticker, current_price, signal.exit_type, current_time))

        for ticker, exit_price, reason, ts in to_close:
            self._close_position(ticker, exit_price, reason, ts)

    async def _scan_and_fill(
        self,
        markets: List[Dict],
        current_time: datetime,
    ) -> None:
        """Scan for opportunities and fill the best ones."""
        existing = {t: True for t in self._open_positions}

        opportunities = await self.strategy.scan_opportunities(
            markets=markets,
            existing_positions=existing,
        )

        slots = self.max_positions - len(self._open_positions)
        for opp in opportunities[:slots]:
            cost = opp.entry_price_cents * self.contracts_per_trade
            commission = self.commission * self.contracts_per_trade

            if cost + commission > self._balance:
                continue

            trade = SimulatedTrade(
                ticker=opp.ticker,
                side=opp.side,
                entry_price_cents=opp.entry_price_cents,
                entry_time=current_time,
                contracts=self.contracts_per_trade,
                strategy_name=opp.strategy_name,
                score=opp.score,
                reasoning=opp.reasoning,
            )
            self._open_positions[opp.ticker] = trade
            self._balance -= cost + commission

    def _force_close_all(
        self,
        price_lookup: Dict[str, Dict],
        close_time: datetime,
    ) -> None:
        """Force-close all remaining positions at last known bid prices."""
        for ticker in list(self._open_positions.keys()):
            market = price_lookup.get(ticker)
            trade = self._open_positions[ticker]

            if market:
                if trade.side == "yes":
                    exit_price = market.get("yes_bid", market.get("last_price", 50))
                else:
                    exit_price = market.get("no_bid", market.get("last_price", 50))
            else:
                # No market data -- close at entry (breakeven assumption)
                exit_price = trade.entry_price_cents

            self._close_position(ticker, exit_price, "force_close", close_time)

    def _close_position(
        self,
        ticker: str,
        exit_price: int,
        exit_reason: str,
        exit_time: datetime,
    ) -> None:
        """Close a position, credit proceeds, record the trade."""
        trade = self._open_positions.pop(ticker)
        trade.exit_price_cents = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = exit_reason

        proceeds = exit_price * trade.contracts
        commission = self.commission * trade.contracts
        self._balance += proceeds - commission

        self._closed_trades.append(trade)
        self._equity_curve.append(self._balance)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _build_result(
        self,
        data_source: str,
        total_timesteps: int,
    ) -> BacktestResult:
        """Compute all metrics from the closed trade list."""
        trades = self._closed_trades
        n = len(trades)

        empty = BacktestResult(
            strategy_name=self.strategy.name,
            strategy_config=self.strategy.config,
            data_source=data_source,
            total_timesteps=total_timesteps,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            breakeven_trades=0,
            win_rate=0.0,
            total_pnl_cents=0,
            avg_pnl_per_trade_cents=0.0,
            largest_win_cents=0,
            largest_loss_cents=0,
            avg_winner_cents=0.0,
            avg_loser_cents=0.0,
            max_drawdown_cents=0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            profit_factor=0.0,
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            initial_balance_cents=self.initial_balance,
            final_balance_cents=self._balance,
            equity_curve=self._equity_curve,
            trades=[],
        )
        if n == 0:
            return empty

        pnls = [t.pnl_cents for t in trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p < 0]
        breakevens = [p for p in pnls if p == 0]

        total_pnl = sum(pnls)
        gross_wins = sum(winners) if winners else 0
        gross_losses = abs(sum(losers)) if losers else 0

        # --- Consecutive streaks ---
        max_consec_w = 0
        max_consec_l = 0
        cur_w = 0
        cur_l = 0
        for p in pnls:
            if p > 0:
                cur_w += 1
                cur_l = 0
                max_consec_w = max(max_consec_w, cur_w)
            elif p < 0:
                cur_l += 1
                cur_w = 0
                max_consec_l = max(max_consec_l, cur_l)
            else:
                cur_w = 0
                cur_l = 0

        # --- Max drawdown from realized equity curve ---
        peak = self.initial_balance
        max_dd_cents = 0
        max_dd_pct = 0.0
        for eq in self._equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd_cents:
                max_dd_cents = dd
                max_dd_pct = dd / peak if peak > 0 else 0.0

        # --- Sharpe ratio ---
        # Per-trade return = pnl / cost_basis, annualized with sqrt(252)
        if n >= 2:
            returns = [
                p / max(t.entry_price_cents * t.contracts, 1)
                for t, p in zip(trades, pnls)
            ]
            mean_ret = statistics.mean(returns)
            std_ret = statistics.stdev(returns)
            sharpe = (mean_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        # --- Profit factor ---
        if gross_losses > 0:
            pf = gross_wins / gross_losses
        elif gross_wins > 0:
            pf = float("inf")
        else:
            pf = 0.0

        return BacktestResult(
            strategy_name=self.strategy.name,
            strategy_config=self.strategy.config,
            data_source=data_source,
            total_timesteps=total_timesteps,
            total_trades=n,
            winning_trades=len(winners),
            losing_trades=len(losers),
            breakeven_trades=len(breakevens),
            win_rate=len(winners) / n,
            total_pnl_cents=total_pnl,
            avg_pnl_per_trade_cents=total_pnl / n,
            largest_win_cents=max(pnls),
            largest_loss_cents=min(pnls),
            avg_winner_cents=statistics.mean(winners) if winners else 0.0,
            avg_loser_cents=statistics.mean(losers) if losers else 0.0,
            max_drawdown_cents=max_dd_cents,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            profit_factor=pf,
            max_consecutive_wins=max_consec_w,
            max_consecutive_losses=max_consec_l,
            initial_balance_cents=self.initial_balance,
            final_balance_cents=self._balance,
            equity_curve=self._equity_curve,
            trades=trades,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_by_timestamp(
        snapshots: List[Dict],
    ) -> List[Tuple[datetime, List[Dict]]]:
        """Group snapshots by _timestamp, sorted chronologically."""
        groups: Dict[datetime, List[Dict]] = {}
        for snap in snapshots:
            ts = snap["_timestamp"]
            groups.setdefault(ts, []).append(snap)
        return sorted(groups.items(), key=lambda x: x[0])

    @staticmethod
    def _parse_timestamp(raw: Any) -> Optional[datetime]:
        """Parse a timestamp from int (unix), str (ISO), or datetime."""
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                try:
                    return datetime.fromtimestamp(float(raw), tz=timezone.utc)
                except (ValueError, OSError):
                    return None
        return None

    @staticmethod
    def _candle_to_snapshot(row: Dict) -> Optional[Dict]:
        """Convert a candlestick row (OHLCV) to a strategy-compatible snapshot.

        Synthesizes bid/ask with a 2c spread around the close price.
        """
        try:
            ts = BacktestRunner._parse_timestamp(
                row.get("end_period_ts") or row.get("timestamp")
            )
            if ts is None:
                return None

            close_price = int(float(row.get("close", 50)))
            close_price = max(3, min(97, close_price))
            volume = int(float(row.get("volume", 0)))
            ticker = row.get("ticker", "UNKNOWN")

            yes_bid = max(1, close_price - 1)
            yes_ask = min(99, close_price + 1)
            no_price = 100 - close_price
            no_bid = max(1, no_price - 1)
            no_ask = min(99, no_price + 1)

            return {
                "_timestamp": ts,
                "ticker": ticker,
                "title": row.get("title", ticker),
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "no_bid": no_bid,
                "no_ask": no_ask,
                "last_price": close_price,
                "volume": volume,
                "volume_24h": volume,
                "open_interest": int(float(row.get("open_interest", 0))),
                "status": row.get("status", "open"),
                "close_time": row.get("close_time"),
            }
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping invalid candle row: {e}")
            return None

    @staticmethod
    def _row_to_snapshot(row: Dict) -> Optional[Dict]:
        """Convert a snapshot-format row to a strategy-compatible dict."""
        try:
            ts = BacktestRunner._parse_timestamp(row.get("timestamp"))
            if ts is None:
                return None

            yes_bid = int(float(row.get("yes_bid", 0)))
            yes_ask = int(float(row.get("yes_ask", 0)))

            return {
                "_timestamp": ts,
                "ticker": row.get("ticker", "UNKNOWN"),
                "title": row.get("title", row.get("ticker", "")),
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "no_bid": int(float(row.get("no_bid", 100 - yes_ask))),
                "no_ask": int(float(row.get("no_ask", 100 - yes_bid))),
                "last_price": (yes_bid + yes_ask) // 2 if (yes_bid and yes_ask) else 50,
                "volume": int(float(row.get("volume", 0))),
                "volume_24h": int(float(row.get("volume_24h", row.get("volume", 0)))),
                "open_interest": int(float(row.get("open_interest", 0))),
                "status": row.get("status", "open"),
                "close_time": row.get("close_time"),
            }
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping invalid snapshot row: {e}")
            return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest a DeepStack trading strategy against historical data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s --strategy mean_reversion --synthetic 500
  %(prog)s --strategy mean_reversion --csv candles.csv --contracts 5
  %(prog)s --strategy momentum --db data.db --query "SELECT * FROM candles"
  %(prog)s -s mean_reversion -n 1000 --seed 123 --balance 50000 -v
""",
    )

    # Strategy
    parser.add_argument(
        "--strategy",
        "-s",
        default="mean_reversion",
        help="Strategy name from the registry (default: mean_reversion)",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help='JSON string of strategy config overrides (e.g. \'{"take_profit_cents": 10}\')',
    )

    # Data source (mutually exclusive)
    data = parser.add_argument_group("data source (pick one)")
    data.add_argument("--csv", default=None, help="Path to CSV file")
    data.add_argument("--db", default=None, help="Path to SQLite database")
    data.add_argument(
        "--query",
        "-q",
        default=None,
        help="SQL query for --db (default: SELECT * FROM market_snapshots)",
    )
    data.add_argument(
        "--table",
        default="market_snapshots",
        help="Table name for --db when no --query (default: market_snapshots)",
    )
    data.add_argument(
        "--synthetic",
        "-n",
        type=int,
        default=None,
        help="Generate N synthetic timesteps (default if no data source given)",
    )
    data.add_argument(
        "--seed", type=int, default=42, help="Random seed for synthetic data (default: 42)"
    )

    # Simulation parameters
    sim = parser.add_argument_group("simulation parameters")
    sim.add_argument(
        "--balance",
        type=int,
        default=15_000,
        help="Initial balance in cents (default: 15000 = $150.00)",
    )
    sim.add_argument(
        "--max-positions",
        type=int,
        default=5,
        help="Max concurrent positions (default: 5)",
    )
    sim.add_argument(
        "--contracts",
        type=int,
        default=1,
        help="Contracts per trade (default: 1)",
    )
    sim.add_argument(
        "--commission",
        type=int,
        default=0,
        help="Commission per contract in cents (default: 0)",
    )

    # Output
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show debug logs and full trade log"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output result as JSON instead of table"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # --- Build strategy ---
    config: Dict[str, Any] = {}
    if args.config:
        config = json.loads(args.config)

    strategy = load_strategy(args.strategy, config)

    # --- Build runner ---
    runner = BacktestRunner(
        strategy=strategy,
        initial_balance_cents=args.balance,
        max_positions=args.max_positions,
        contracts_per_trade=args.contracts,
        commission_cents_per_contract=args.commission,
    )

    # --- Load data ---
    if args.csv:
        snapshots = BacktestRunner.load_csv(args.csv)
        source = f"csv: {args.csv}"
    elif args.db:
        snapshots = BacktestRunner.load_sqlite(args.db, query=args.query, table=args.table)
        source = f"sqlite: {args.db}"
    else:
        count = args.synthetic or 500
        snapshots = BacktestRunner.generate_synthetic(timesteps=count, seed=args.seed)
        source = f"synthetic ({count} steps, seed={args.seed})"

    # --- Run ---
    result = asyncio.run(runner.run(snapshots, data_source=source))

    # --- Output ---
    if args.json:
        output = {
            "strategy": result.strategy_name,
            "config": result.strategy_config,
            "data_source": result.data_source,
            "timesteps": result.total_timesteps,
            "total_trades": result.total_trades,
            "win_rate": round(result.win_rate, 4),
            "total_pnl_cents": result.total_pnl_cents,
            "avg_pnl_per_trade_cents": round(result.avg_pnl_per_trade_cents, 2),
            "max_drawdown_cents": result.max_drawdown_cents,
            "max_drawdown_pct": round(result.max_drawdown_pct, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "profit_factor": round(result.profit_factor, 4) if result.profit_factor != float("inf") else "inf",
            "initial_balance_cents": result.initial_balance_cents,
            "final_balance_cents": result.final_balance_cents,
        }
        print(json.dumps(output, indent=2))
    else:
        print(result.summary())

    # Trade log in verbose mode
    if args.verbose and result.trades:
        print("\n  TRADE LOG")
        print("  " + "-" * 68)
        for i, t in enumerate(result.trades, 1):
            duration = ""
            if t.entry_time and t.exit_time:
                hrs = (t.exit_time - t.entry_time).total_seconds() / 3600
                duration = f" ({hrs:.1f}h)"
            print(
                f"  {i:3d}. {t.ticker} {t.side.upper():3s} "
                f"in={t.entry_price_cents}c out={t.exit_price_cents}c "
                f"pnl={t.pnl_cents:+d}c [{t.exit_reason}]{duration}"
            )


if __name__ == "__main__":
    main()
