"""
Backtest package for DeepStack trading strategies.

Replays historical market data through the same Strategy interface
used in production, tracking simulated P&L and risk metrics.
"""

from .runner import BacktestRunner, BacktestResult, SimulatedTrade

__all__ = ["BacktestRunner", "BacktestResult", "SimulatedTrade"]
