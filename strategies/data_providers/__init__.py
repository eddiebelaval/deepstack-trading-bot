"""
External Data Providers for Trading Strategies

Provides async interfaces to external data sources:
- WeatherDataProvider: NWS + Open-Meteo weather forecasts
- NewsDataProvider: RSS feed aggregation (NYT, BBC, Reuters)
- LLMProvider: Claude Sonnet for strategy-level analysis
"""

from .weather import WeatherDataProvider, WeatherForecast
from .news import NewsDataProvider, NewsEvent
from .llm import LLMProvider

__all__ = [
    "WeatherDataProvider",
    "WeatherForecast",
    "NewsDataProvider",
    "NewsEvent",
    "LLMProvider",
]
