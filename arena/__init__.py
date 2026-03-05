"""
DeepStack Strategy Arena — Walk-Forward Tournament Engine

Battle-test all strategies against historical data using walk-forward
validation, composite scoring, and automatic promotion/demotion.

Usage:
    python -m arena                    # Synthetic data, default config
    python -m arena --synthetic 10000  # More timesteps
    python -m arena --csv candles.csv  # CSV data
    python -m arena --json             # JSON output
"""

from .config import ArenaConfig
from .engine import TournamentEngine
from .models import RegimeFitness, StrategyScore, TournamentResult
from .seas import SEAS, SeaCondition, SeaGenerator

__all__ = [
    "ArenaConfig",
    "TournamentEngine",
    "RegimeFitness",
    "StrategyScore",
    "TournamentResult",
    "SEAS",
    "SeaCondition",
    "SeaGenerator",
]
