"""
Composite Scorer — Percentile-Rank Normalization + Weighted Composite

Scores strategies within a single walk-forward window. Each metric is
normalized 0-100 relative to other strategies (percentile rank), then
combined via weighted sum.

Key design decisions:
- Percentile-rank (not absolute thresholds) ensures meaningful ordering
  even when all strategies perform poorly.
- max_drawdown_pct is inverted (lower = better score).
- profit_factor capped at 10.0 before normalization to prevent outliers.
- 0-trade strategies get composite = 0 (dead strategy penalty).
- Strategies with <5 trades get a (count/5) multiplier penalty.
"""

import logging
import sys
from pathlib import Path
from typing import Dict, List

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arena.config import ArenaConfig
from arena.models import StrategyScore

logger = logging.getLogger(__name__)

# Avoid division by zero in percentile calc
_EPSILON = 1e-9

# Cap profit_factor to prevent infinity/outlier distortion
_PF_CAP = 10.0

# Minimum trades before full credit
_MIN_TRADE_THRESHOLD = 5


class CompositeScorer:
    """Score and rank strategies within a single walk-forward window."""

    def __init__(self, config: ArenaConfig):
        self.config = config
        self.weights = config.weights

    def score_window(
        self,
        results: Dict[str, "BacktestResult"],
        window_id: int,
    ) -> List[StrategyScore]:
        """Score all strategies from a single OOS window.

        Args:
            results: Map of strategy_name -> BacktestResult from that window.
            window_id: The window identifier.

        Returns:
            List of StrategyScore objects sorted by composite_score descending.
        """
        if not results:
            return []

        # Extract raw metrics from BacktestResults
        raw_metrics: Dict[str, Dict[str, float]] = {}
        for name, result in results.items():
            pf = result.profit_factor
            if pf == float("inf"):
                pf = _PF_CAP
            pf = min(pf, _PF_CAP)

            raw_metrics[name] = {
                "win_rate": result.win_rate,
                "sharpe_ratio": result.sharpe_ratio,
                "profit_factor": pf,
                "max_drawdown_pct": result.max_drawdown_pct,
                "avg_pnl": result.avg_pnl_per_trade_cents,
                "trade_count": float(result.total_trades),
            }

        # Percentile-rank normalize each metric across strategies
        metric_names = list(self.weights.keys())
        percentiles: Dict[str, Dict[str, float]] = {
            name: {} for name in raw_metrics
        }

        for metric in metric_names:
            values = [raw_metrics[name][metric] for name in raw_metrics]
            for name in raw_metrics:
                val = raw_metrics[name][metric]
                if metric == "max_drawdown_pct":
                    # Invert: lower drawdown = higher percentile
                    percentiles[name][metric] = self._percentile_rank_inverted(
                        val, values
                    )
                else:
                    # Higher = better
                    percentiles[name][metric] = self._percentile_rank(
                        val, values
                    )

        # Compute weighted composite scores
        scores: List[StrategyScore] = []
        for name, result in results.items():
            composite = sum(
                self.weights[metric] * percentiles[name][metric]
                for metric in metric_names
            )

            # Dead strategy penalty: 0 trades = 0 score
            if result.total_trades == 0:
                composite = 0.0
            # Low trade count penalty
            elif result.total_trades < _MIN_TRADE_THRESHOLD:
                multiplier = result.total_trades / _MIN_TRADE_THRESHOLD
                composite *= multiplier

            pf = result.profit_factor
            if pf == float("inf"):
                pf = _PF_CAP

            scores.append(StrategyScore(
                strategy_name=name,
                window_id=window_id,
                win_rate=result.win_rate,
                sharpe_ratio=result.sharpe_ratio,
                profit_factor=min(pf, _PF_CAP),
                max_drawdown_pct=result.max_drawdown_pct,
                total_pnl_cents=result.total_pnl_cents,
                total_trades=result.total_trades,
                avg_pnl_cents=result.avg_pnl_per_trade_cents,
                composite_score=round(composite, 2),
            ))

        # Rank by composite descending
        scores.sort(key=lambda s: s.composite_score, reverse=True)
        for i, score in enumerate(scores):
            score.rank = i + 1

        return scores

    @staticmethod
    def compute_fitness_matrix(
        regime_scores: Dict[str, List["StrategyScore"]],
    ) -> Dict[str, Dict[str, float]]:
        """Normalize per-regime composite scores to 0.0-1.0 fitness values.

        For each regime, the max composite score maps to 1.0 and others
        are proportional. Zero-score strategies stay at 0.0.

        Args:
            regime_scores: Dict of regime_name -> list of aggregated
                StrategyScore objects (from TournamentResult.regime_scores).

        Returns:
            {strategy_name: {regime: fitness_score}} ready for the
            governance router's strategy_regime_fitness table.
        """
        matrix: Dict[str, Dict[str, float]] = {}

        for regime, scores in regime_scores.items():
            if not scores:
                continue

            max_composite = max(s.composite_score for s in scores)
            if max_composite <= 0:
                # All strategies scored 0 in this regime
                for s in scores:
                    matrix.setdefault(s.strategy_name, {})[regime] = 0.0
                continue

            for s in scores:
                fitness = s.composite_score / max_composite
                fitness = round(max(0.0, min(1.0, fitness)), 4)
                matrix.setdefault(s.strategy_name, {})[regime] = fitness

        return matrix

    @staticmethod
    def _percentile_rank(value: float, all_values: List[float]) -> float:
        """Percentile rank: fraction of values <= this value, scaled 0-100.

        If all values are equal, everyone gets 50.
        """
        n = len(all_values)
        if n <= 1:
            return 50.0

        val_range = max(all_values) - min(all_values)
        if val_range < _EPSILON:
            return 50.0

        count_below = sum(1 for v in all_values if v < value)
        count_equal = sum(1 for v in all_values if abs(v - value) < _EPSILON)
        # Use midpoint method for ties
        rank = (count_below + 0.5 * count_equal) / n
        return rank * 100.0

    @staticmethod
    def _percentile_rank_inverted(
        value: float, all_values: List[float]
    ) -> float:
        """Inverted percentile rank: lower value = higher score."""
        n = len(all_values)
        if n <= 1:
            return 50.0

        val_range = max(all_values) - min(all_values)
        if val_range < _EPSILON:
            return 50.0

        count_above = sum(1 for v in all_values if v > value)
        count_equal = sum(1 for v in all_values if abs(v - value) < _EPSILON)
        rank = (count_above + 0.5 * count_equal) / n
        return rank * 100.0
