"""
External Data Providers for Trading Strategies

Provides async interfaces to external data sources:
- WeatherDataProvider: NWS + Open-Meteo weather forecasts
- NewsDataProvider: RSS feed aggregation (NYT, BBC, Reuters)
- LLMProvider: Claude Sonnet for strategy-level analysis
- CryptoPriceFeed: Real-time BTC/ETH/SOL prices from CoinGecko
- FredDataProvider: Economic indicators from FRED (Fed rate, CPI, GDP, unemployment)
- TradingViewDataProvider: Top backtested TradingView indicators from Supabase
"""

from .weather import WeatherDataProvider, WeatherForecast
from .news import NewsDataProvider, NewsEvent
from .llm import LLMProvider
from .crypto import CryptoPriceFeed
from .fred import FredDataProvider
from .tradingview import TradingViewDataProvider

__all__ = [
    "WeatherDataProvider",
    "WeatherForecast",
    "NewsDataProvider",
    "NewsEvent",
    "LLMProvider",
    "CryptoPriceFeed",
    "FredDataProvider",
    "TradingViewDataProvider",
]
