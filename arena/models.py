"""
Arena Data Models

Dataclasses for the walk-forward tournament system. These are pure data
containers with no external dependencies beyond the standard library.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4


@dataclass
class WalkForwardWindow:
    """A single walk-forward validation window.

    The in-sample (IS) period precedes the out-of-sample (OOS) period.
    In v1, only OOS is used for scoring — IS is reserved for future
    parameter optimization.

    Timeline: [--- IS ---][--- OOS ---]
    """

    window_id: int
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime
    is_snapshot_count: int = 0
    oos_snapshot_count: int = 0
    regime_label: Optional[str] = None


@dataclass
class StrategyScore:
    """Scored result for one strategy in one tournament window (or aggregated).

    Raw metrics come directly from BacktestResult. The composite_score
    is computed by CompositeScorer using percentile-rank normalization.
    """

    strategy_name: str
    window_id: Optional[int]  # None for aggregated scores

    # Raw metrics from BacktestResult
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    total_pnl_cents: int = 0
    total_trades: int = 0
    avg_pnl_cents: float = 0.0

    # Computed by CompositeScorer
    composite_score: float = 0.0
    rank: int = 0


@dataclass
class TournamentResult:
    """Complete result of a tournament run across all windows and strategies."""

    tournament_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    data_source: str = ""

    # Per-strategy aggregated rankings (sorted by composite_score descending)
    rankings: List[StrategyScore] = field(default_factory=list)

    # Per-window per-strategy scores
    window_scores: Dict[int, List[StrategyScore]] = field(default_factory=dict)

    # Per-regime per-strategy scores (seas mode)
    regime_scores: Dict[str, List[StrategyScore]] = field(default_factory=dict)

    # Strategy names that errored during run
    errors: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def total_windows(self) -> int:
        return len(self.window_scores)

    @property
    def total_strategies(self) -> int:
        return len(self.rankings)


@dataclass
class RegimeFitness:
    """Fitness score for a strategy in a specific market regime.

    Produced by normalizing arena composite scores (0-100) to the
    governance fitness range (0.0-1.0). Max strategy per regime gets 1.0.
    """

    strategy_name: str
    regime: str
    fitness_score: float  # 0.0-1.0
    sample_size: int  # number of windows scored
    confidence: float  # 0.0-1.0, based on sample_size and score variance


@dataclass
class PromotionCandidate:
    """A strategy evaluated for promotion/demotion based on tournament results."""

    strategy_name: str
    avg_composite_score: float

    # Averaged metrics across all windows
    avg_win_rate: float = 0.0
    avg_sharpe: float = 0.0
    avg_profit_factor: float = 0.0
    avg_max_drawdown_pct: float = 0.0
    avg_pnl_cents: float = 0.0
    total_trades_across_windows: int = 0

    # One of: promote_paper, promote_live, demote, hold
    recommendation: str = "hold"
