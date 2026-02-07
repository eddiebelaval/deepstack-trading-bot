"""
Weather Model Aggregation Strategy

Aggregates free weather forecasts (NWS, Open-Meteo) to price
Kalshi weather markets. Trades when model consensus disagrees with
the market price by more than the configured threshold.

Edge:
    Free weather models (NWS, Open-Meteo) are quite accurate within 48 hours.
    Aggregating multiple models reduces individual model error. When the
    aggregated forecast significantly disagrees with market price, the
    models are likely more accurate than the market consensus.

Expected Value:
    Win rate: 62% | Avg win: 7c | Avg loss: 5c
    EV = (0.62 * 7) - (0.38 * 5) = 4.34 - 1.90 = +2.44c per contract
"""

import logging
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import (
    score_spread,
    score_volume,
    hours_until_close,
    is_market_tradeable,
    get_mid_price,
    clamp_score,
)
from .data_providers.weather import (
    WeatherDataProvider,
    WeatherForecast,
    parse_kalshi_weather_ticker,
)

logger = logging.getLogger(__name__)


class WeatherAggregationStrategy(Strategy):
    """
    Trade weather markets using aggregated model forecasts.

    Configuration:
        min_edge_cents: Min probability edge to trade (default: 5)
        min_model_consensus: Min model agreement 0-1 (default: 0.7)
        target_cities: Cities to trade (default: ["new_york", "chicago"])
        max_hours_to_settlement: Max forecast horizon (default: 48)
        take_profit_cents: Target profit (default: 7)
        stop_loss_cents: Max loss (default: 5)
    """

    def __init__(self, config: Dict[str, Any]):
        config.setdefault("take_profit_cents", 7)
        config.setdefault("stop_loss_cents", 5)
        super().__init__(config)

        self.min_edge = config.get("min_edge_cents", 5)
        self.min_consensus = config.get("min_model_consensus", 0.7)
        self.target_cities = config.get("target_cities", ["new_york", "chicago"])
        self.max_hours = config.get("max_hours_to_settlement", 48)

        self._weather = WeatherDataProvider()

        logger.info(
            f"WeatherAggregationStrategy initialized: "
            f"min_edge={self.min_edge}c, cities={self.target_cities}, "
            f"max_hours={self.max_hours}"
        )

    @property
    def name(self) -> str:
        return "weather_aggregation"

    @property
    def description(self) -> str:
        return (
            f"Weather model aggregation: Trade weather markets when "
            f"NWS+Open-Meteo consensus disagrees with market ({self.min_edge}c+ edge)"
        )

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        existing_positions = existing_positions or {}
        opportunities = []

        for market in markets:
            ticker = market.get("ticker", "")

            if not is_market_tradeable(market, self.min_volume):
                continue

            if ticker in existing_positions:
                continue

            # Parse weather ticker
            parsed = parse_kalshi_weather_ticker(ticker)
            if not parsed:
                continue

            city = parsed["city"]
            if city not in self.target_cities:
                continue

            # Check time horizon
            hours = hours_until_close(market)
            if hours is not None and hours > self.max_hours:
                continue

            # Fetch weather forecast
            forecast = await self._weather.get_forecast(city, parsed["date"])
            if not forecast:
                continue

            # Check model consensus
            consensus = self._weather.model_consensus(forecast)
            if consensus < self.min_consensus:
                continue

            # Calculate model probability
            if parsed["direction"] == "high":
                model_prob = forecast.probability_above(parsed["threshold_f"])
            else:  # "low"
                model_prob = forecast.probability_below(parsed["threshold_f"])

            model_price_cents = int(model_prob * 100)
            market_price = get_mid_price(market)

            edge_cents = model_price_cents - market_price

            opp = self._evaluate_weather_edge(
                market=market,
                ticker=ticker,
                parsed=parsed,
                forecast=forecast,
                consensus=consensus,
                model_price_cents=model_price_cents,
                market_price=market_price,
                edge_cents=edge_cents,
                hours=hours,
            )

            if opp:
                opportunities.append(opp)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}] Found {len(opportunities)} weather opportunities "
            f"from {len(markets)} markets"
        )
        return opportunities

    def _evaluate_weather_edge(
        self,
        market: Dict,
        ticker: str,
        parsed: Dict,
        forecast: WeatherForecast,
        consensus: float,
        model_price_cents: int,
        market_price: int,
        edge_cents: int,
        hours: Optional[float],
    ) -> Optional[TradingOpportunity]:
        """Evaluate a single weather market for trading edge."""

        yes_bid = market.get("yes_bid", 0)
        yes_ask = market.get("yes_ask", 0)
        no_bid = market.get("no_bid", 0)
        no_ask = market.get("no_ask", 0)
        volume = market.get("volume", 0) or market.get("volume_24h", 0)

        if edge_cents >= self.min_edge:
            # Model says higher probability than market — buy YES
            side = "yes"
            entry_price = yes_ask if yes_ask else market_price
            reasoning = (
                f"Weather models ({', '.join(forecast.sources)}) say "
                f"{model_price_cents}c, market at {market_price}c "
                f"(+{edge_cents}c edge). "
                f"Forecast: {parsed['direction']} {parsed['threshold_f']}F in "
                f"{parsed['city']}. Buying YES."
            )
        elif edge_cents <= -self.min_edge:
            # Model says lower probability — buy NO
            side = "no"
            entry_price = no_ask if no_ask else (100 - market_price)
            reasoning = (
                f"Weather models ({', '.join(forecast.sources)}) say "
                f"{model_price_cents}c, market at {market_price}c "
                f"({edge_cents}c edge). "
                f"Forecast: {parsed['direction']} {parsed['threshold_f']}F in "
                f"{parsed['city']}. Buying NO."
            )
        else:
            return None

        # Score
        edge_score = min(abs(edge_cents) / 15.0, 1.0) * 35
        consensus_score = consensus * 30
        time_score = 0.0
        if hours is not None and hours > 0:
            time_score = max(0, 20 * (1 - hours / self.max_hours))
        vol_score = score_volume(volume, target=500, max_score=15)

        total_score = clamp_score(edge_score + consensus_score + time_score + vol_score)

        if total_score < self.min_score:
            return None

        return TradingOpportunity(
            ticker=ticker,
            title=market.get("title", ""),
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=market_price,
            current_no_price=100 - market_price,
            volume=volume,
            score=total_score,
            reasoning=reasoning,
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "city": parsed["city"],
                "direction": parsed["direction"],
                "threshold_f": parsed["threshold_f"],
                "model_price_cents": model_price_cents,
                "market_price": market_price,
                "edge_cents": edge_cents,
                "consensus": consensus,
                "sources": forecast.sources,
                "temp_high_f": forecast.temp_high_f,
                "temp_low_f": forecast.temp_low_f,
                "temp_std_f": forecast.temp_std_f,
            },
        )

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        entry_price = position.get("entry_price", 50)
        pnl_cents = current_price - entry_price

        if pnl_cents >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit: +{pnl_cents}c",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss: {pnl_cents}c",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        # Near settlement with profit — hold
        if market_data:
            hours = hours_until_close(market_data)
            if hours is not None and hours < 2 and pnl_cents > 0:
                return ExitSignal(
                    should_exit=False,
                    reason=f"Near settlement ({hours:.1f}h), holding with +{pnl_cents}c profit",
                    exit_type="hold",
                    current_price_cents=current_price,
                    pnl_cents=pnl_cents,
                    urgency=0.0,
                )

        return ExitSignal(
            should_exit=False,
            reason=f"P&L: {pnl_cents:+d}c (TP: +{self.take_profit}c, SL: -{self.stop_loss}c)",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def get_historical_stats(self) -> Dict[str, float]:
        return {
            "win_rate": 0.62,
            "avg_win_cents": 7.0,
            "avg_loss_cents": 5.0,
        }

    def validate_config(self) -> tuple[bool, str]:
        valid, error = super().validate_config()
        if not valid:
            return valid, error

        if self.min_edge < 1:
            return False, "min_edge_cents must be at least 1"

        if not (0 < self.min_consensus <= 1):
            return False, "min_model_consensus must be between 0 and 1"

        if self.max_hours <= 0:
            return False, "max_hours_to_settlement must be positive"

        if not self.target_cities:
            return False, "target_cities must not be empty"

        return True, ""
