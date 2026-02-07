"""
Weather Data Provider

Aggregates forecasts from free weather APIs:
- NWS (api.weather.gov) — US National Weather Service
- Open-Meteo (open-meteo.com) — Global free weather API

Used by WeatherAggregationStrategy to price weather-related prediction markets.
"""

import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# City -> NWS grid coordinates (office/gridX/gridY) and Open-Meteo lat/lon
CITY_STATIONS: Dict[str, Dict[str, Any]] = {
    "new_york": {
        "nws_office": "OKX",
        "nws_grid_x": 33,
        "nws_grid_y": 37,
        "lat": 40.7128,
        "lon": -74.0060,
        "name": "New York City",
    },
    "chicago": {
        "nws_office": "LOT",
        "nws_grid_x": 76,
        "nws_grid_y": 73,
        "lat": 41.8781,
        "lon": -87.6298,
        "name": "Chicago",
    },
    "los_angeles": {
        "nws_office": "LOX",
        "nws_grid_x": 154,
        "nws_grid_y": 44,
        "lat": 34.0522,
        "lon": -118.2437,
        "name": "Los Angeles",
    },
    "miami": {
        "nws_office": "MFL",
        "nws_grid_x": 110,
        "nws_grid_y": 50,
        "lat": 25.7617,
        "lon": -80.1918,
        "name": "Miami",
    },
    "austin": {
        "nws_office": "EWX",
        "nws_grid_x": 156,
        "nws_grid_y": 91,
        "lat": 30.2672,
        "lon": -97.7431,
        "name": "Austin",
    },
}

# Kalshi weather ticker aliases
TICKER_CITY_ALIASES: Dict[str, str] = {
    "nyc": "new_york",
    "ny": "new_york",
    "chi": "chicago",
    "la": "los_angeles",
    "lax": "los_angeles",
    "mia": "miami",
    "aus": "austin",
}


@dataclass
class WeatherForecast:
    """
    Aggregated weather forecast from multiple sources.

    Attributes:
        city: City identifier
        date: Forecast date
        temp_high_f: Forecasted high temperature (Fahrenheit)
        temp_low_f: Forecasted low temperature (Fahrenheit)
        temp_std_f: Standard deviation of forecasts (uncertainty)
        precip_probability: Probability of precipitation (0-1)
        sources: List of source names that contributed
        fetched_at: When this forecast was retrieved
    """

    city: str
    date: datetime
    temp_high_f: float
    temp_low_f: float
    temp_std_f: float = 3.0  # Default uncertainty
    precip_probability: float = 0.0
    sources: List[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.now)

    def probability_above(self, threshold_f: float) -> float:
        """
        Probability that actual high temp exceeds threshold.
        Uses normal approximation around forecasted high.
        """
        if self.temp_std_f <= 0:
            return 1.0 if self.temp_high_f > threshold_f else 0.0

        z = (threshold_f - self.temp_high_f) / self.temp_std_f
        return 1.0 - _normal_cdf(z)

    def probability_below(self, threshold_f: float) -> float:
        """
        Probability that actual low temp falls below threshold.
        Uses normal approximation around forecasted low.
        """
        if self.temp_std_f <= 0:
            return 1.0 if self.temp_low_f < threshold_f else 0.0

        z = (threshold_f - self.temp_low_f) / self.temp_std_f
        return _normal_cdf(z)


def _normal_cdf(z: float) -> float:
    """Approximate standard normal CDF using error function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def parse_kalshi_weather_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    """
    Parse Kalshi weather market ticker to extract city/date/threshold.

    Kalshi weather tickers follow patterns like:
    - HIGHNY-26FEB07-T50  (High temp NYC, Feb 7 2026, threshold 50F)
    - LOWCHI-26FEB07-T20  (Low temp Chicago, Feb 7 2026, threshold 20F)

    Returns:
        Dict with city, date, threshold_f, direction or None if not parseable
    """
    ticker_upper = ticker.upper()

    # Match patterns like HIGHNY-26FEB07-T50 or LOWCHI-26FEB07-T20
    pattern = r"(HIGH|LOW)(\w{2,3})-(\d{2}\w{3}\d{2})-T(-?\d+)"
    match = re.match(pattern, ticker_upper)
    if not match:
        return None

    direction = match.group(1).lower()  # "high" or "low"
    city_code = match.group(2).lower()
    date_str = match.group(3)
    threshold = int(match.group(4))

    # Resolve city
    city = TICKER_CITY_ALIASES.get(city_code, city_code)
    if city not in CITY_STATIONS:
        return None

    # Parse date
    try:
        date = datetime.strptime(date_str, "%y%b%d")
    except ValueError:
        return None

    return {
        "city": city,
        "date": date,
        "threshold_f": threshold,
        "direction": direction,
    }


class WeatherDataProvider:
    """
    Async weather data aggregator.

    Fetches from NWS and Open-Meteo, caches results for 30 minutes.
    """

    CACHE_TTL_SECONDS = 1800  # 30 minutes

    def __init__(self):
        self._cache: Dict[str, Tuple[float, WeatherForecast]] = {}
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "KalshiTradingBot/1.0 (contact@id8labs.tech)"},
            )
        return self._client

    async def get_forecast(self, city: str, target_date: datetime) -> Optional[WeatherForecast]:
        """
        Get aggregated weather forecast for a city and date.

        Args:
            city: City identifier (e.g., "new_york")
            target_date: Date to forecast

        Returns:
            WeatherForecast or None if unavailable
        """
        cache_key = f"{city}_{target_date.strftime('%Y%m%d')}"

        # Check cache
        if cache_key in self._cache:
            cached_time, cached_forecast = self._cache[cache_key]
            if time.time() - cached_time < self.CACHE_TTL_SECONDS:
                return cached_forecast

        station = CITY_STATIONS.get(city)
        if not station:
            logger.warning(f"Unknown city: {city}")
            return None

        forecasts: List[Dict[str, float]] = []

        # Fetch from NWS
        nws_data = await self._fetch_nws(station, target_date)
        if nws_data:
            forecasts.append(nws_data)

        # Fetch from Open-Meteo
        meteo_data = await self._fetch_open_meteo(station, target_date)
        if meteo_data:
            forecasts.append(meteo_data)

        if not forecasts:
            return None

        # Aggregate
        highs = [f["high_f"] for f in forecasts if "high_f" in f]
        lows = [f["low_f"] for f in forecasts if "low_f" in f]
        precips = [f.get("precip_prob", 0.0) for f in forecasts]
        sources = [f["source"] for f in forecasts]

        avg_high = sum(highs) / len(highs) if highs else 50.0
        avg_low = sum(lows) / len(lows) if lows else 30.0

        # Estimate uncertainty from model disagreement
        if len(highs) >= 2:
            temp_std = max(2.0, (max(highs) - min(highs)) / 2.0 + 2.0)
        else:
            temp_std = 4.0  # Higher uncertainty with single source

        forecast = WeatherForecast(
            city=city,
            date=target_date,
            temp_high_f=avg_high,
            temp_low_f=avg_low,
            temp_std_f=temp_std,
            precip_probability=sum(precips) / len(precips) if precips else 0.0,
            sources=sources,
        )

        self._cache[cache_key] = (time.time(), forecast)
        return forecast

    async def _fetch_nws(
        self, station: Dict[str, Any], target_date: datetime
    ) -> Optional[Dict[str, Any]]:
        """Fetch forecast from NWS API."""
        try:
            client = await self._get_client()
            office = station["nws_office"]
            grid_x = station["nws_grid_x"]
            grid_y = station["nws_grid_y"]

            url = f"https://api.weather.gov/gridpoints/{office}/{grid_x},{grid_y}/forecast"
            resp = await client.get(url)
            resp.raise_for_status()

            data = resp.json()
            periods = data.get("properties", {}).get("periods", [])

            target_str = target_date.strftime("%Y-%m-%d")
            day_temps = []
            night_temps = []

            for period in periods:
                start = period.get("startTime", "")
                if target_str in start:
                    temp = period.get("temperature")
                    if temp is not None:
                        if period.get("isDaytime", True):
                            day_temps.append(temp)
                        else:
                            night_temps.append(temp)

            if day_temps or night_temps:
                return {
                    "source": "nws",
                    "high_f": max(day_temps) if day_temps else (max(night_temps) + 10),
                    "low_f": min(night_temps) if night_temps else (min(day_temps) - 10),
                    "precip_prob": 0.0,  # NWS forecast doesn't always include this simply
                }
        except Exception as e:
            logger.debug(f"NWS fetch failed for {station.get('name', '?')}: {e}")

        return None

    async def _fetch_open_meteo(
        self, station: Dict[str, Any], target_date: datetime
    ) -> Optional[Dict[str, Any]]:
        """Fetch forecast from Open-Meteo API."""
        try:
            client = await self._get_client()
            lat = station["lat"]
            lon = station["lon"]
            date_str = target_date.strftime("%Y-%m-%d")

            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                f"&temperature_unit=fahrenheit"
                f"&start_date={date_str}&end_date={date_str}"
                f"&timezone=America%2FNew_York"
            )
            resp = await client.get(url)
            resp.raise_for_status()

            data = resp.json()
            daily = data.get("daily", {})
            highs = daily.get("temperature_2m_max", [])
            lows = daily.get("temperature_2m_min", [])
            precips = daily.get("precipitation_probability_max", [])

            if highs and lows:
                return {
                    "source": "open_meteo",
                    "high_f": highs[0],
                    "low_f": lows[0],
                    "precip_prob": (precips[0] / 100.0) if precips else 0.0,
                }
        except Exception as e:
            logger.debug(f"Open-Meteo fetch failed for {station.get('name', '?')}: {e}")

        return None

    def model_consensus(self, forecast: WeatherForecast) -> float:
        """
        Calculate model consensus score (0-1).

        Higher = more sources agree. Single source = 0.5.
        """
        n = len(forecast.sources)
        if n == 0:
            return 0.0
        if n == 1:
            return 0.5

        # More sources with lower std = higher consensus
        std_factor = max(0.0, 1.0 - forecast.temp_std_f / 10.0)
        return min(1.0, 0.5 + std_factor * 0.5)

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
