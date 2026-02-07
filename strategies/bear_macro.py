"""
Bear Market Macro Strategy

Trades economic indicator markets (Fed rates, CPI, GDP, unemployment)
using FRED data to calculate probability estimates and detect
bull/bear market regimes.

Target markets: KXFED, KXCPI, KXGDP, KXJOBS

Lower frequency (2-5 signals/month) since economic data releases are
monthly/quarterly, but higher edge per trade due to fundamental analysis.

Expected Value:
    win_rate=0.58, avg_win=10c, avg_loss=7c
    EV = (0.58 * 10) - (0.42 * 7) = 5.80 - 2.94 = +2.86c/contract
"""

import logging
import re
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .data_providers.fred import FredDataProvider
from .utils import get_mid_price, is_market_tradeable

logger = logging.getLogger(__name__)

# Map Kalshi series to FRED series + signal calculator
SERIES_MAP = {
    "KXFED": {"fred_series": "FEDFUNDS", "type": "fed"},
    "KXCPI": {"fred_series": "CPIAUCSL", "type": "cpi"},
    "KXGDP": {"fred_series": "GDP", "type": "gdp"},
    "KXJOBS": {"fred_series": "UNRATE", "type": "jobs"},
}


class BearMacroStrategy(Strategy):
    """
    Macro economic indicator trading using FRED data.

    Logic:
    1. Fetch latest economic data from FRED
    2. Detect market regime (bull/bear/neutral)
    3. Calculate probability estimate for each macro contract
    4. Compare to Kalshi market price to find edge
    5. In bear markets, boost weight on recession-aligned signals

    Configuration:
        - min_edge_cents: Minimum edge to trade (default 5)
        - bear_mode_only: Only trade in bear regime (default false)
        - take_profit_cents: Target profit (default 10)
        - stop_loss_cents: Max loss (default 7)
        - min_volume: Minimum market volume (default 50)
        - max_hold_hours: Max hold time (default 168 = 1 week)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_edge = config.get("min_edge_cents", 5)
        self.bear_mode_only = config.get("bear_mode_only", False)
        self.max_hold_hours = config.get("max_hold_hours", 168)
        self._fred = FredDataProvider()

        logger.info(
            f"BearMacroStrategy initialized: "
            f"min_edge={self.min_edge}c, bear_only={self.bear_mode_only}, "
            f"TP=+{self.take_profit}c, SL=-{self.stop_loss}c"
        )

    @property
    def name(self) -> str:
        return "bear_macro"

    @property
    def description(self) -> str:
        return "Bear market macro strategy using FRED economic indicators"

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        existing_positions = existing_positions or {}
        opportunities = []

        # Get regime signals first
        regime = await self._fred.get_regime_signals()
        regime_score = regime.get("regime_score", 0.0)

        # If bear_mode_only and we're not in a bear regime, skip
        if self.bear_mode_only and regime_score > -0.2:
            logger.info(
                f"[{self.name}] Regime score {regime_score:.2f} not bearish enough, skipping"
            )
            return []

        for market in markets:
            ticker = market.get("ticker", "")
            if ticker in existing_positions:
                continue

            if not is_market_tradeable(market, min_volume=self.min_volume):
                continue

            series = market.get("series_ticker", "")
            if series not in SERIES_MAP:
                continue

            config = SERIES_MAP[series]
            fred_data = await self._fred.get_latest(config["fred_series"], periods=12)
            if not fred_data:
                continue

            opp = self._analyze_macro_market(
                market, config["type"], fred_data, regime_score
            )
            if opp:
                opportunities.append(opp)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}] Found {len(opportunities)} opportunities "
            f"(regime_score: {regime_score:.2f})"
        )
        return opportunities

    def _analyze_macro_market(
        self,
        market: Dict[str, Any],
        signal_type: str,
        fred_data: List[Dict[str, Any]],
        regime_score: float,
    ) -> Optional[TradingOpportunity]:
        """Analyze a single macro market against FRED data."""
        ticker = market.get("ticker", "")
        title = market.get("title", "")
        volume = market.get("volume", 0) or market.get("volume_24h", 0)
        mid_price = get_mid_price(market)
        yes_ask = market.get("yes_ask", 0)
        no_ask = market.get("no_ask", 0)

        # Calculate signal based on type
        calculators = {
            "fed": self._calculate_fed_signal,
            "cpi": self._calculate_cpi_signal,
            "gdp": self._calculate_gdp_signal,
            "jobs": self._calculate_jobs_signal,
        }

        calc = calculators.get(signal_type)
        if not calc:
            return None

        fair_value, reasoning_detail = calc(fred_data, title)
        if fair_value is None:
            return None

        # Edge calculation
        edge = fair_value - mid_price

        # In bear regimes, boost edges on recession-aligned bets
        if regime_score < -0.3:
            # Bear regime amplifies signals that align with recession
            if signal_type == "fed" and edge > 0:
                edge *= 1.2  # Rate cuts more likely in recession
            elif signal_type == "jobs" and fair_value > 50:
                edge *= 1.2  # Higher unemployment more likely
            elif signal_type == "gdp" and fair_value < 50:
                edge *= 1.2  # Lower GDP growth more likely

        if abs(edge) < self.min_edge:
            return None

        # Determine side
        if edge > 0:
            side = "yes"
            entry_price = yes_ask if yes_ask else mid_price
        else:
            side = "no"
            entry_price = no_ask if no_ask else (100 - mid_price)

        entry_price = max(1, min(99, entry_price))

        # Score: edge magnitude + regime alignment
        score = min(100, abs(edge) * 5 + abs(regime_score) * 20)

        return TradingOpportunity(
            ticker=ticker,
            title=title,
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=mid_price,
            current_no_price=100 - mid_price,
            volume=volume,
            score=max(0, score),
            reasoning=(
                f"Macro {signal_type}: fair_value={fair_value:.0f}c vs market={mid_price}c | "
                f"edge={edge:+.0f}c | regime={regime_score:.2f} | {reasoning_detail}"
            ),
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "signal_type": signal_type,
                "fair_value": fair_value,
                "edge": edge,
                "regime_score": regime_score,
            },
        )

    def _calculate_fed_signal(
        self, data: List[Dict[str, Any]], title: str
    ) -> tuple:
        """
        Fed funds rate signal.
        Trend analysis: rising rates = hawkish, falling = dovish.
        """
        if len(data) < 2:
            return None, ""

        current = data[0]["value"]
        prev = data[1]["value"]
        trend = current - prev

        # Parse target from title (e.g., "Fed rate above 5.25%")
        target = self._parse_rate_from_title(title)
        if target is None:
            return None, ""

        # Simple probability estimate: if current is above target, YES is likely
        if current > target:
            fair_value = 70 + min(20, (current - target) * 40)
        elif current < target:
            fair_value = 30 - min(20, (target - current) * 40)
        else:
            fair_value = 50

        # Adjust for trend
        if trend > 0:
            fair_value = min(95, fair_value + 5)  # Rising rates
        elif trend < 0:
            fair_value = max(5, fair_value - 5)  # Falling rates

        detail = f"rate={current:.2f}%, target={target:.2f}%, trend={trend:+.2f}"
        return fair_value, detail

    def _calculate_cpi_signal(
        self, data: List[Dict[str, Any]], title: str
    ) -> tuple:
        """CPI signal: inflation trend analysis."""
        if len(data) < 3:
            return None, ""

        current = data[0]["value"]
        prev_1 = data[1]["value"]
        prev_2 = data[2]["value"]

        # Month-over-month changes
        mom_1 = ((current - prev_1) / prev_1) * 100 if prev_1 else 0
        mom_2 = ((prev_1 - prev_2) / prev_2) * 100 if prev_2 else 0
        trend = mom_1 - mom_2  # Accelerating or decelerating

        # Parse target from title
        target = self._parse_rate_from_title(title)
        if target is None:
            # Default: estimate if CPI will rise
            fair_value = 55 if mom_1 > 0 else 45
            detail = f"CPI={current:.1f}, MoM={mom_1:.2f}%, trend={trend:+.2f}"
            return fair_value, detail

        yoy_change = ((current - data[-1]["value"]) / data[-1]["value"]) * 100 if len(data) > 11 else mom_1 * 12

        if yoy_change > target:
            fair_value = 65 + min(25, (yoy_change - target) * 10)
        else:
            fair_value = 35 - min(25, (target - yoy_change) * 10)

        detail = f"CPI={current:.1f}, YoY~{yoy_change:.1f}%, target={target:.1f}%"
        return fair_value, detail

    def _calculate_gdp_signal(
        self, data: List[Dict[str, Any]], title: str
    ) -> tuple:
        """GDP signal: growth trend and contraction probability."""
        if len(data) < 2:
            return None, ""

        current = data[0]["value"]
        prev = data[1]["value"]
        growth = ((current - prev) / abs(prev)) * 100 if prev else 0

        target = self._parse_rate_from_title(title)

        if target is not None:
            if growth > target:
                fair_value = 65 + min(25, (growth - target) * 15)
            else:
                fair_value = 35 - min(25, (target - growth) * 15)
        else:
            # Default: will GDP be positive?
            fair_value = 60 if growth > 0 else 40
            if growth < -0.5:
                fair_value = max(5, 30 + growth * 10)  # Strong contraction signal

        detail = f"GDP={current:.1f}B, growth={growth:+.1f}%"
        return fair_value, detail

    def _calculate_jobs_signal(
        self, data: List[Dict[str, Any]], title: str
    ) -> tuple:
        """Unemployment signal: rate trend analysis."""
        if len(data) < 2:
            return None, ""

        current = data[0]["value"]
        prev = data[1]["value"]
        trend = current - prev

        target = self._parse_rate_from_title(title)
        if target is None:
            # Default: probability unemployment rises
            fair_value = 55 if trend > 0 else 45
            detail = f"UNRATE={current:.1f}%, trend={trend:+.1f}"
            return fair_value, detail

        if current > target:
            fair_value = 70 + min(20, (current - target) * 20)
        else:
            fair_value = 30 - min(20, (target - current) * 20)

        # Trend adjustment
        if trend > 0:
            fair_value = min(95, fair_value + 3)
        elif trend < 0:
            fair_value = max(5, fair_value - 3)

        detail = f"UNRATE={current:.1f}%, target={target:.1f}%, trend={trend:+.2f}"
        return fair_value, detail

    @staticmethod
    def _parse_rate_from_title(title: str) -> Optional[float]:
        """Extract a numeric rate/percentage from contract title."""
        patterns = [
            r'(\d+\.?\d*)%',
            r'above\s+(\d+\.?\d*)',
            r'below\s+(\d+\.?\d*)',
            r'at\s+(\d+\.?\d*)',
        ]
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                return float(match.group(1))
        return None

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
                reason=f"Take profit: +{pnl_cents}c (target: +{self.take_profit}c)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss: {pnl_cents}c (limit: -{self.stop_loss}c)",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        # Time-based exit for macro positions
        entry_time = position.get("entry_time")
        if entry_time:
            from datetime import datetime, timezone
            try:
                if isinstance(entry_time, str):
                    et = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                else:
                    et = entry_time
                elapsed_hours = (datetime.now(timezone.utc) - et).total_seconds() / 3600
                if elapsed_hours >= self.max_hold_hours:
                    return ExitSignal(
                        should_exit=True,
                        reason=f"Max hold time ({self.max_hold_hours}h) exceeded",
                        exit_type="expiry",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.6,
                    )
            except (ValueError, TypeError):
                pass

        return ExitSignal(
            should_exit=False,
            reason=f"P&L: {pnl_cents:+d}c (TP: +{self.take_profit}c, SL: -{self.stop_loss}c)",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        return {
            "win_rate": 0.58,
            "avg_win_cents": float(self.take_profit),   # 10c
            "avg_loss_cents": float(self.stop_loss),     # 7c
        }
