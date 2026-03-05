"""
Tournament Engine — Walk-Forward Validation Across All Strategies

Orchestrates BacktestRunner to run every eligible strategy through
rolling out-of-sample windows, then scores and ranks them.

Walk-Forward Algorithm:
    1. Load snapshots, find T_start and T_end
    2. cursor = T_start; while cursor + IS + OOS <= T_end:
       create window, advance cursor += step
    3. Per window, per strategy: fresh instance + BacktestRunner.run(oos_data)
    4. Score each window via CompositeScorer
    5. Aggregate mean composite per strategy across all windows
    6. Rank descending
"""

import asyncio
import logging
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arena.config import ArenaConfig
from arena.models import StrategyScore, TournamentResult, WalkForwardWindow
from arena.scoring import CompositeScorer
from arena.seas import SeaGenerator
from backtest.runner import BacktestResult, BacktestRunner
from strategies import STRATEGY_REGISTRY, load_strategy

logger = logging.getLogger(__name__)


class TournamentEngine:
    """Run all strategies through walk-forward validation windows."""

    def __init__(self, config: ArenaConfig):
        config.validate()
        self.config = config
        self.scorer = CompositeScorer(config)

    async def run_tournament(
        self,
        strategy_names: Optional[List[str]] = None,
    ) -> TournamentResult:
        """Run a full tournament.

        Args:
            strategy_names: Specific strategies to run. If None, runs all
                eligible strategies (those in STRATEGY_REGISTRY minus excluded).

        Returns:
            TournamentResult with rankings and per-window scores.
        """
        result = TournamentResult(
            started_at=datetime.now(timezone.utc),
            data_source=self.config.data_source,
        )

        # Determine which strategies to run
        names = strategy_names or self._eligible_strategies()
        logger.info(f"Tournament: {len(names)} strategies — {', '.join(names)}")

        if self.config.seas_mode:
            return await self._run_seas_tournament(result, names)

        # Load data
        snapshots = self._load_data()
        if not snapshots:
            logger.error("No snapshots loaded — aborting tournament")
            result.finished_at = datetime.now(timezone.utc)
            return result

        logger.info(f"Loaded {len(snapshots)} snapshots")

        # Generate walk-forward windows
        windows = self._generate_windows(snapshots)
        if not windows:
            logger.error("No valid windows generated — aborting tournament")
            result.finished_at = datetime.now(timezone.utc)
            return result

        logger.info(f"Generated {len(windows)} walk-forward windows")

        # Run each strategy through each OOS window
        all_window_scores: Dict[int, List[StrategyScore]] = {}

        for window in windows:
            oos_data = self._slice_data(
                snapshots, window.oos_start, window.oos_end
            )
            window.oos_snapshot_count = len(oos_data)

            if not oos_data:
                logger.warning(
                    f"Window {window.window_id}: no OOS data, skipping"
                )
                continue

            logger.info(
                f"Window {window.window_id}: "
                f"OOS {window.oos_start:%Y-%m-%d} to {window.oos_end:%Y-%m-%d} "
                f"({len(oos_data)} snapshots)"
            )

            # Run all strategies on this window's OOS data
            window_results: Dict[str, BacktestResult] = {}
            for name in names:
                bt_result = await self._run_strategy_on_window(
                    name, oos_data, window.window_id
                )
                if bt_result is not None:
                    window_results[name] = bt_result
                else:
                    result.errors.setdefault(name, []).append(
                        f"window_{window.window_id}"
                    )

            # Score this window
            if window_results:
                scores = self.scorer.score_window(
                    window_results, window.window_id
                )
                all_window_scores[window.window_id] = scores

        result.window_scores = all_window_scores

        # Aggregate across windows
        result.rankings = self._aggregate_scores(all_window_scores, names)
        result.finished_at = datetime.now(timezone.utc)

        duration = (result.finished_at - result.started_at).total_seconds()
        logger.info(
            f"Tournament complete: {len(result.rankings)} strategies ranked "
            f"across {result.total_windows} windows in {duration:.1f}s"
        )

        return result

    async def _run_seas_tournament(
        self,
        result: TournamentResult,
        names: List[str],
    ) -> TournamentResult:
        """Run a multi-regime seas tournament.

        For each sea condition:
        1. Generate regime-specific synthetic data
        2. Create walk-forward windows (tagged with regime_label)
        3. Run all strategies through each window
        4. Score and aggregate per-regime

        Then aggregate across all regimes for overall rankings.
        """
        result.data_source = "seas"
        seas_data = self._load_seas_data()

        if not seas_data:
            logger.error("No seas data generated — aborting")
            result.finished_at = datetime.now(timezone.utc)
            return result

        all_window_scores: Dict[int, List[StrategyScore]] = {}
        global_window_id = 0

        for regime_name, snapshots in seas_data.items():
            logger.info(
                f"--- Sea: {regime_name} ({len(snapshots)} snapshots) ---"
            )

            windows = self._generate_windows(snapshots)
            if not windows:
                logger.warning(f"Sea '{regime_name}': no valid windows, skipping")
                continue

            logger.info(
                f"Sea '{regime_name}': {len(windows)} walk-forward windows"
            )

            regime_window_scores: Dict[int, List[StrategyScore]] = {}

            for window in windows:
                window.regime_label = regime_name
                # Remap window_id to global to avoid collisions across seas
                window.window_id = global_window_id

                oos_data = self._slice_data(
                    snapshots, window.oos_start, window.oos_end
                )
                window.oos_snapshot_count = len(oos_data)

                if not oos_data:
                    global_window_id += 1
                    continue

                window_results: Dict[str, BacktestResult] = {}
                for name in names:
                    bt_result = await self._run_strategy_on_window(
                        name, oos_data, window.window_id
                    )
                    if bt_result is not None:
                        window_results[name] = bt_result
                    else:
                        result.errors.setdefault(name, []).append(
                            f"window_{window.window_id}_{regime_name}"
                        )

                if window_results:
                    scores = self.scorer.score_window(
                        window_results, window.window_id
                    )
                    all_window_scores[window.window_id] = scores
                    regime_window_scores[window.window_id] = scores

                global_window_id += 1

            # Per-regime aggregation
            if regime_window_scores:
                regime_rankings = self._aggregate_scores(
                    regime_window_scores, names
                )
                result.regime_scores[regime_name] = regime_rankings
                logger.info(
                    f"Sea '{regime_name}': top strategy = "
                    f"{regime_rankings[0].strategy_name} "
                    f"(score={regime_rankings[0].composite_score})"
                    if regime_rankings else f"Sea '{regime_name}': no rankings"
                )

        result.window_scores = all_window_scores

        # Overall aggregation across all seas
        result.rankings = self._aggregate_scores(all_window_scores, names)
        result.finished_at = datetime.now(timezone.utc)

        duration = (result.finished_at - result.started_at).total_seconds()
        logger.info(
            f"Seas tournament complete: {len(result.rankings)} strategies "
            f"ranked across {len(seas_data)} seas, "
            f"{result.total_windows} total windows in {duration:.1f}s"
        )

        return result

    def _eligible_strategies(self) -> List[str]:
        """Return strategy names eligible for tournament (not excluded)."""
        excluded = set(self.config.exclude_strategies)
        return [
            name for name in STRATEGY_REGISTRY
            if name not in excluded
        ]

    def _load_data(self) -> List[Dict]:
        """Load snapshots based on config data source."""
        source = self.config.data_source

        if source == "csv" and self.config.data_path:
            return BacktestRunner.load_csv(self.config.data_path)
        elif source == "sqlite" and self.config.data_path:
            return BacktestRunner.load_sqlite(
                self.config.data_path,
                query=self.config.data_query,
            )
        else:
            # Default: synthetic
            return BacktestRunner.generate_synthetic(
                timesteps=self.config.synthetic_timesteps,
                seed=self.config.synthetic_seed,
            )

    def _load_seas_data(self) -> Dict[str, List[Dict]]:
        """Load multi-regime synthetic data using SeaGenerator."""
        generator = SeaGenerator()
        return generator.generate_all_seas(
            timesteps_per_sea=self.config.seas_timesteps_per_regime,
            seed=self.config.synthetic_seed,
            regimes=self.config.seas_regimes,
        )

    def _generate_windows(
        self, snapshots: List[Dict]
    ) -> List[WalkForwardWindow]:
        """Generate rolling walk-forward windows from the data timerange.

        Each window has an IS period (for future parameter optimization)
        and an OOS period (for scoring). Windows advance by step_months.
        """
        if not snapshots:
            return []

        t_start = snapshots[0]["_timestamp"]
        t_end = snapshots[-1]["_timestamp"]

        is_delta = timedelta(days=self.config.is_months * 30)
        oos_delta = timedelta(days=self.config.oos_months * 30)
        step_delta = timedelta(days=self.config.step_months * 30)

        windows = []
        cursor = t_start
        window_id = 0

        while cursor + is_delta + oos_delta <= t_end:
            is_start = cursor
            is_end = cursor + is_delta
            oos_start = is_end
            oos_end = oos_start + oos_delta

            windows.append(WalkForwardWindow(
                window_id=window_id,
                is_start=is_start,
                is_end=is_end,
                oos_start=oos_start,
                oos_end=oos_end,
            ))

            cursor += step_delta
            window_id += 1

        return windows

    @staticmethod
    def _slice_data(
        snapshots: List[Dict],
        start: datetime,
        end: datetime,
    ) -> List[Dict]:
        """Filter snapshots to those within [start, end)."""
        return [
            s for s in snapshots
            if start <= s["_timestamp"] < end
        ]

    async def _run_strategy_on_window(
        self,
        strategy_name: str,
        oos_data: List[Dict],
        window_id: int,
    ) -> Optional[BacktestResult]:
        """Run a single strategy on a single OOS window.

        Creates a fresh strategy instance and BacktestRunner per call
        to avoid state leakage between windows.

        Returns None if the strategy errors or times out.
        """
        try:
            strategy = load_strategy(strategy_name, {})
            runner = BacktestRunner(
                strategy=strategy,
                initial_balance_cents=self.config.initial_balance_cents,
                max_positions=self.config.max_positions,
                contracts_per_trade=self.config.contracts_per_trade,
            )

            bt_result = await asyncio.wait_for(
                runner.run(
                    oos_data,
                    data_source=f"arena_window_{window_id}",
                ),
                timeout=self.config.strategy_timeout_seconds,
            )
            return bt_result

        except asyncio.TimeoutError:
            logger.warning(
                f"{strategy_name} timed out on window {window_id} "
                f"({self.config.strategy_timeout_seconds}s limit)"
            )
            return None
        except Exception as e:
            logger.warning(
                f"{strategy_name} errored on window {window_id}: {e}"
            )
            return None

    @staticmethod
    def _aggregate_scores(
        all_window_scores: Dict[int, List[StrategyScore]],
        strategy_names: List[str],
    ) -> List[StrategyScore]:
        """Aggregate per-window scores into mean composite per strategy.

        Returns a sorted list of StrategyScore with window_id=None
        (indicating aggregated result).
        """
        if not all_window_scores:
            return []

        # Collect per-strategy scores across all windows
        strategy_scores: Dict[str, List[StrategyScore]] = {}
        for scores in all_window_scores.values():
            for score in scores:
                strategy_scores.setdefault(score.strategy_name, []).append(score)

        # Compute mean for each strategy
        aggregated: List[StrategyScore] = []
        for name in strategy_names:
            scores = strategy_scores.get(name, [])
            if not scores:
                continue

            n = len(scores)
            aggregated.append(StrategyScore(
                strategy_name=name,
                window_id=None,
                win_rate=statistics.mean(s.win_rate for s in scores),
                sharpe_ratio=statistics.mean(s.sharpe_ratio for s in scores),
                profit_factor=statistics.mean(s.profit_factor for s in scores),
                max_drawdown_pct=statistics.mean(
                    s.max_drawdown_pct for s in scores
                ),
                total_pnl_cents=sum(s.total_pnl_cents for s in scores),
                total_trades=sum(s.total_trades for s in scores),
                avg_pnl_cents=statistics.mean(s.avg_pnl_cents for s in scores),
                composite_score=round(
                    statistics.mean(s.composite_score for s in scores), 2
                ),
            ))

        # Rank by composite descending
        aggregated.sort(key=lambda s: s.composite_score, reverse=True)
        for i, score in enumerate(aggregated):
            score.rank = i + 1

        return aggregated
