"""
Kalshi Trading Bot - S&P 500 Hourly Prediction Markets

A production-ready trading bot for Kalshi prediction markets that uses
DeepStack's risk management (Kelly Criterion + Emotional Firewall) for
disciplined position sizing and emotional control.

Features:
    - RSA-authenticated API integration with Kalshi
    - Multi-strategy plugin architecture
    - Mean-reversion and momentum strategies
    - Kelly Criterion position sizing with safety caps
    - Emotional firewall to prevent impulsive trading
    - SQLite trade journal for analysis and audit
    - Graceful shutdown with order cleanup
    - YAML-based configuration with profiles

Example (Legacy Mode):
    >>> from kalshi_trader import KalshiTradingBot
    >>> bot = KalshiTradingBot()
    >>> await bot.start()

Example (Multi-Strategy Mode):
    >>> from kalshi_trader import KalshiTradingBot
    >>> from kalshi_trader.config import load_config
    >>> config = load_config(profile="aggressive")
    >>> bot = KalshiTradingBot(config, use_strategy_manager=True)
    >>> await bot.start()

CLI Usage:
    python run_bot.py                              # Legacy mode
    python run_bot.py --multi                      # Multi-strategy mode
    python run_bot.py --profile=aggressive         # Use profile
    python run_bot.py --strategies=mean_reversion,momentum  # Specific strategies
"""

from .config import (
    KalshiConfig,
    load_config,
    get_strategy_configs,
    load_profile,
    load_yaml_config,
)
from .exceptions import (
    KalshiTradingError,
    KalshiAuthError,
    KalshiRateLimitError,
    KalshiOrderError,
    RiskLimitExceeded,
    DailyLossLimitHit,
)
from .kalshi_client import AuthenticatedKalshiClient
from .deepstack_integration import DeepStackIntegration
from .strategy import MeanReversionStrategy
from .journal import TradeJournal
from .main import KalshiTradingBot
from .market_governor import (
    BleedDetector,
    CycleAnalyzer,
    GovernanceEngine,
    MarketRegime,
    RegimePrediction,
    StrategyRouter,
)
from .strategy_manager import StrategyManager
from .captains_log import CaptainsLog, NarrationEvent, EventPriority
from .trade_analyzer import TradeAnalyzer

__all__ = [
    # Main bot
    "KalshiTradingBot",
    # Configuration
    "KalshiConfig",
    "load_config",
    "get_strategy_configs",
    "load_profile",
    "load_yaml_config",
    # Components
    "AuthenticatedKalshiClient",
    "DeepStackIntegration",
    "MeanReversionStrategy",
    "TradeJournal",
    "BleedDetector",
    "CycleAnalyzer",
    "GovernanceEngine",
    "MarketRegime",
    "RegimePrediction",
    "StrategyRouter",
    "StrategyManager",
    "TradeAnalyzer",
    "CaptainsLog",
    "NarrationEvent",
    "EventPriority",
    # Exceptions
    "KalshiTradingError",
    "KalshiAuthError",
    "KalshiRateLimitError",
    "KalshiOrderError",
    "RiskLimitExceeded",
    "DailyLossLimitHit",
]

__version__ = "0.2.0"
