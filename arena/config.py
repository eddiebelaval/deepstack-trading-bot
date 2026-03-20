"""
Arena Configuration

ArenaConfig dataclass with sensible defaults for walk-forward tournaments.
All timing is in months to match typical backtesting convention.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ArenaConfig:
    """Configuration for a tournament run.

    Walk-Forward Parameters:
        is_months: In-sample training window length (reserved for future use).
        oos_months: Out-of-sample evaluation window length.
        step_months: How far to advance the window each iteration.

    Backtest Parameters:
        initial_balance_cents: Starting cash per strategy per window.
        max_positions: Max concurrent open positions per strategy.
        contracts_per_trade: Fixed contract count per entry.

    Scoring Weights:
        Must sum to 1.0. Each metric is percentile-rank normalized (0-100)
        then weighted. Higher composite = better strategy.

    Promotion Thresholds:
        promote_paper: Min avg composite to recommend paper trading.
        promote_live: Min avg composite to recommend live deployment.
        demote: Max avg composite before recommending disablement.
    """

    # Walk-forward timing
    is_months: int = 6
    oos_months: int = 1
    step_months: int = 1

    # Backtest parameters
    initial_balance_cents: int = 15_000
    max_positions: int = 5
    contracts_per_trade: int = 1

    # Scoring weights (must sum to 1.0)
    weight_sharpe_ratio: float = 0.30
    weight_profit_factor: float = 0.25
    weight_win_rate: float = 0.15
    weight_max_drawdown_pct: float = 0.15
    weight_avg_pnl: float = 0.10
    weight_trade_count: float = 0.05

    # Promotion thresholds (composite score 0-100)
    promote_paper_threshold: float = 50.0
    promote_live_threshold: float = 65.0
    demote_threshold: float = 30.0

    # Strategies that need external data and can't be backtested
    exclude_strategies: List[str] = field(default_factory=lambda: [
        "cross_platform_arbitrage",  # Needs Polymarket data
        "tv_signals",                # Needs TradingView webhook data
        # stock_momentum v2 now works with synthetic data (MACD/RSI/VWAP on any price series)
    ])

    # Data source (set via CLI)
    data_source: str = "synthetic"  # synthetic, csv, sqlite, kalshi_api
    data_path: Optional[str] = None
    data_query: Optional[str] = None
    synthetic_timesteps: int = 10000
    synthetic_seed: int = 42

    # Seas mode (multi-regime tournament)
    seas_mode: bool = False
    seas_regimes: Optional[List[str]] = None  # None = all 5 seas
    seas_timesteps_per_regime: int = 10000
    update_fitness: bool = False  # Show proposed fitness changes
    fitness_db_path: str = "trade_journal.db"  # Governance DB path

    # Timeouts
    strategy_timeout_seconds: float = 60.0

    # Maximum strategies to enable in config.yaml
    max_enabled_strategies: int = 5

    def validate(self) -> None:
        """Raise ValueError if config is invalid."""
        weights = (
            self.weight_sharpe_ratio
            + self.weight_profit_factor
            + self.weight_win_rate
            + self.weight_max_drawdown_pct
            + self.weight_avg_pnl
            + self.weight_trade_count
        )
        if abs(weights - 1.0) > 0.01:
            raise ValueError(
                f"Scoring weights must sum to 1.0, got {weights:.3f}"
            )
        if self.oos_months < 1:
            raise ValueError("oos_months must be >= 1")
        if self.step_months < 1:
            raise ValueError("step_months must be >= 1")
        if self.initial_balance_cents <= 0:
            raise ValueError("initial_balance_cents must be positive")

    @property
    def weights(self) -> dict:
        """Return scoring weights as a dict keyed by metric name."""
        return {
            "sharpe_ratio": self.weight_sharpe_ratio,
            "profit_factor": self.weight_profit_factor,
            "win_rate": self.weight_win_rate,
            "max_drawdown_pct": self.weight_max_drawdown_pct,
            "avg_pnl": self.weight_avg_pnl,
            "trade_count": self.weight_trade_count,
        }
