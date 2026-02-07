"""
Crypto Intraday Strategy

Trades short-timeframe crypto markets (KXBTC, KXETH, KXSOL) using
4 signal sources: external momentum, fair value edge, volatility harvest,
and orderbook imbalance.

Absorbs the volatility harvester concept as one of the signal sources
(buys underpriced side when spreads exceed 2x normal width).

Target markets: 15-min and hourly crypto contracts on Kalshi.

Expected Value:
    win_rate=0.58, avg_win=6c, avg_loss=4c
    EV = (0.58 * 6) - (0.42 * 4) = 3.48 - 1.68 = +1.80c/contract
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .data_providers.crypto import CryptoPriceFeed
from .utils import get_mid_price, is_market_tradeable

logger = logging.getLogger(__name__)

# Signal weights for composite scoring
SIGNAL_WEIGHTS = {
    "external_momentum": 0.30,
    "fair_value_edge": 0.35,
    "volatility_harvest": 0.20,
    "orderbook_imbalance": 0.15,
}

# Crypto symbol extraction from Kalshi series tickers
SERIES_TO_SYMBOL = {
    "KXBTC": "BTC",
    "KXETH": "ETH",
    "KXSOL": "SOL",
}

# Typical spread widths in cents for volatility harvest baseline
TYPICAL_SPREAD = {
    "BTC": 4,
    "ETH": 5,
    "SOL": 6,
}

# Estimated hourly volatility (in % of price) for normal CDF
EST_HOURLY_VOL = {
    "BTC": 0.015,   # 1.5% per hour
    "ETH": 0.020,   # 2.0% per hour
    "SOL": 0.030,   # 3.0% per hour
}


def _normal_cdf(x: float) -> float:
    """
    Polynomial approximation of the standard normal CDF.

    Uses Abramowitz & Stegun formula 26.2.17 (max error 7.5e-8).
    Avoids scipy dependency.
    """
    if x < -8.0:
        return 0.0
    if x > 8.0:
        return 1.0

    sign = 1.0 if x >= 0 else -1.0
    x = abs(x)

    t = 1.0 / (1.0 + 0.2316419 * x)
    d = 0.3989422804014327  # 1/sqrt(2*pi)
    prob = d * math.exp(-x * x / 2.0) * t * (
        0.319381530
        + t * (-0.356563782
        + t * (1.781477937
        + t * (-1.821255978
        + t * 1.330274429)))
    )

    return 0.5 + sign * (0.5 - prob)


def _parse_strike_from_title(title: str) -> Optional[float]:
    """
    Extract strike price from contract title.

    Examples:
        "Bitcoin above $95,000 at 3pm ET" -> 95000.0
        "ETH above $3,500" -> 3500.0
        "Solana above $200.50" -> 200.5
    """
    patterns = [
        r'\$([0-9,]+(?:\.[0-9]+)?)',   # $95,000 or $200.50
        r'above\s+([0-9,]+(?:\.[0-9]+)?)',  # above 95000
        r'below\s+([0-9,]+(?:\.[0-9]+)?)',  # below 95000
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def _detect_symbol(market: Dict[str, Any]) -> Optional[str]:
    """Detect crypto symbol from market series_ticker or ticker."""
    series = market.get("series_ticker", "")
    if series in SERIES_TO_SYMBOL:
        return SERIES_TO_SYMBOL[series]

    ticker = market.get("ticker", "").upper()
    for prefix, symbol in SERIES_TO_SYMBOL.items():
        if ticker.startswith(prefix):
            return symbol
    return None


class CryptoIntradayStrategy(Strategy):
    """
    Intraday crypto trading on Kalshi using external price feeds
    and multi-signal composite scoring.

    4 signal sources:
    1. External momentum (30%): CoinGecko price direction vs Kalshi contract
    2. Fair value edge (35%): Our probability estimate vs market price
    3. Volatility harvest (20%): Buy underpriced side when spreads are wide
    4. Orderbook imbalance (15%): Bid/ask depth asymmetry

    Configuration:
        - price_source: "coingecko" (only supported source)
        - min_edge_cents: Minimum edge to trade (default 3)
        - take_profit_cents: Target profit (default 6)
        - stop_loss_cents: Max loss (default 4)
        - min_volume: Minimum market volume (default 50)
        - max_hold_minutes: Max hold time (default 45)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_edge = config.get("min_edge_cents", 3)
        self.max_hold_minutes = config.get("max_hold_minutes", 45)
        self._price_feed = CryptoPriceFeed()

        logger.info(
            f"CryptoIntradayStrategy initialized: "
            f"min_edge={self.min_edge}c, TP=+{self.take_profit}c, "
            f"SL=-{self.stop_loss}c"
        )

    @property
    def name(self) -> str:
        return "crypto_intraday"

    @property
    def description(self) -> str:
        return "Intraday crypto trading with external price feeds and multi-signal scoring"

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        existing_positions = existing_positions or {}
        opportunities = []

        # Batch fetch crypto prices
        symbols_needed = set()
        for market in markets:
            sym = _detect_symbol(market)
            if sym:
                symbols_needed.add(sym)

        if not symbols_needed:
            return []

        prices = await self._price_feed.get_prices(list(symbols_needed))

        for market in markets:
            ticker = market.get("ticker", "")
            if ticker in existing_positions:
                continue

            if not is_market_tradeable(market, min_volume=self.min_volume):
                continue

            symbol = _detect_symbol(market)
            if not symbol or symbol not in prices:
                continue

            external_price = prices[symbol]
            opp = self._analyze_market(market, symbol, external_price)
            if opp:
                opportunities.append(opp)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}] Found {len(opportunities)} opportunities "
            f"from {len(markets)} markets (prices: {prices})"
        )
        return opportunities

    def _analyze_market(
        self,
        market: Dict[str, Any],
        symbol: str,
        external_price: float,
    ) -> Optional[TradingOpportunity]:
        """Analyze a single crypto market using 4 signal sources."""
        ticker = market.get("ticker", "")
        title = market.get("title", "")
        yes_bid = market.get("yes_bid", 0)
        yes_ask = market.get("yes_ask", 0)
        no_bid = market.get("no_bid", 0)
        no_ask = market.get("no_ask", 0)
        volume = market.get("volume", 0) or market.get("volume_24h", 0)

        mid_price = get_mid_price(market)
        strike = _parse_strike_from_title(title)

        # --- Signal 1: External Momentum ---
        momentum_signal = self._calc_momentum_signal(symbol, external_price, strike, mid_price)

        # --- Signal 2: Fair Value Edge ---
        fv_signal, fair_value, edge_cents = self._calc_fair_value_signal(
            symbol, external_price, strike, mid_price
        )

        # --- Signal 3: Volatility Harvest ---
        vol_signal = self._calc_volatility_signal(symbol, yes_bid, yes_ask, no_bid, no_ask)

        # --- Signal 4: Orderbook Imbalance ---
        imbalance_signal = self._calc_imbalance_signal(yes_bid, yes_ask, no_bid, no_ask)

        # Composite score (0-100)
        composite = (
            momentum_signal * SIGNAL_WEIGHTS["external_momentum"]
            + fv_signal * SIGNAL_WEIGHTS["fair_value_edge"]
            + vol_signal * SIGNAL_WEIGHTS["volatility_harvest"]
            + imbalance_signal * SIGNAL_WEIGHTS["orderbook_imbalance"]
        )

        # Require minimum edge and score
        if abs(edge_cents) < self.min_edge and composite < self.min_score:
            return None

        # Determine side from fair value
        if fair_value > 0 and mid_price < fair_value:
            side = "yes"
            entry_price = yes_ask if yes_ask else mid_price
        elif fair_value > 0 and mid_price > fair_value:
            side = "no"
            entry_price = no_ask if no_ask else (100 - mid_price)
        else:
            # No clear directional signal
            return None

        # Clamp entry price to valid range
        entry_price = max(1, min(99, entry_price))

        reasoning = (
            f"{symbol} @ ${external_price:,.0f} | strike: ${strike:,.0f} | "
            f"fair_value: {fair_value:.0f}c vs market: {mid_price}c | "
            f"edge: {edge_cents:+.0f}c | composite: {composite:.1f}"
            if strike else
            f"{symbol} @ ${external_price:,.0f} | "
            f"composite: {composite:.1f} | momentum+vol signals"
        )

        return TradingOpportunity(
            ticker=ticker,
            title=title,
            side=side,
            entry_price_cents=entry_price,
            current_yes_price=mid_price,
            current_no_price=100 - mid_price,
            volume=volume,
            score=min(100, max(0, composite)),
            reasoning=reasoning,
            expected_profit_cents=self.take_profit,
            max_loss_cents=self.stop_loss,
            strategy_name=self.name,
            metadata={
                "symbol": symbol,
                "external_price": external_price,
                "strike": strike,
                "fair_value": fair_value,
                "edge_cents": edge_cents,
                "momentum_signal": momentum_signal,
                "fv_signal": fv_signal,
                "vol_signal": vol_signal,
                "imbalance_signal": imbalance_signal,
            },
        )

    def _calc_momentum_signal(
        self,
        symbol: str,
        external_price: float,
        strike: Optional[float],
        mid_price: int,
    ) -> float:
        """External price direction relative to contract expectation. 0-100."""
        if not strike or external_price <= 0:
            return 50.0  # Neutral

        # If external price is above strike, YES should be high
        distance_pct = (external_price - strike) / strike
        implied_prob = mid_price / 100.0

        # Agreement between direction and price = bullish signal
        if distance_pct > 0 and implied_prob < 0.6:
            # External says above strike, market says <60% — buy YES
            return min(100, 50 + abs(distance_pct) * 2000)
        elif distance_pct < 0 and implied_prob > 0.4:
            # External says below strike, market says >40% — buy NO
            return min(100, 50 + abs(distance_pct) * 2000)
        return 50.0

    def _calc_fair_value_signal(
        self,
        symbol: str,
        external_price: float,
        strike: Optional[float],
        mid_price: int,
    ) -> tuple:
        """
        Calculate fair value probability and edge.

        Uses normal CDF with estimated hourly volatility.
        Returns: (signal_score, fair_value_cents, edge_cents)
        """
        if not strike or external_price <= 0:
            return 50.0, 0.0, 0.0

        vol = EST_HOURLY_VOL.get(symbol, 0.02)
        if vol <= 0:
            return 50.0, 0.0, 0.0

        # z-score: how many std devs is strike from current price?
        z = (external_price - strike) / (external_price * vol)

        # Probability that price will be above strike
        prob_above = _normal_cdf(z)
        fair_value = prob_above * 100  # in cents

        edge_cents = fair_value - mid_price

        # Convert edge to signal score
        signal = 50 + edge_cents * 3  # 3 points per cent of edge
        return max(0, min(100, signal)), fair_value, edge_cents

    def _calc_volatility_signal(
        self,
        symbol: str,
        yes_bid: int,
        yes_ask: int,
        no_bid: int,
        no_ask: int,
    ) -> float:
        """
        Volatility harvest: wide spreads indicate mispricing opportunity.
        Returns 0-100 signal.
        """
        yes_spread = (yes_ask - yes_bid) if (yes_ask and yes_bid) else 0
        no_spread = (no_ask - no_bid) if (no_ask and no_bid) else 0
        avg_spread = (yes_spread + no_spread) / 2

        typical = TYPICAL_SPREAD.get(symbol, 5)
        if typical <= 0:
            return 50.0

        # Signal increases when spread is wider than typical
        spread_ratio = avg_spread / typical
        if spread_ratio > 2.0:
            return min(100, 60 + (spread_ratio - 2.0) * 20)
        elif spread_ratio > 1.5:
            return 55
        return 40  # Tight spreads = less opportunity

    def _calc_imbalance_signal(
        self,
        yes_bid: int,
        yes_ask: int,
        no_bid: int,
        no_ask: int,
    ) -> float:
        """
        Orderbook imbalance: asymmetric depth suggests directional pressure.
        Returns 0-100 signal.
        """
        if not (yes_bid and yes_ask and no_bid and no_ask):
            return 50.0

        # YES-side strength: bid close to ask = strong demand
        yes_tightness = yes_ask - yes_bid
        no_tightness = no_ask - no_bid

        if yes_tightness + no_tightness == 0:
            return 50.0

        # Ratio favoring tighter side (more aggressive quoting)
        imbalance = (no_tightness - yes_tightness) / (yes_tightness + no_tightness)
        return max(0, min(100, 50 + imbalance * 30))

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        entry_price = position.get("entry_price", 50)
        pnl_cents = current_price - entry_price

        # Take profit
        if pnl_cents >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit: +{pnl_cents}c (target: +{self.take_profit}c)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        # Stop loss
        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss: {pnl_cents}c (limit: -{self.stop_loss}c)",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        # Time-based exit (for intraday strategy, time matters more)
        entry_time = position.get("entry_time")
        if entry_time and market_data:
            from datetime import datetime, timezone
            try:
                if isinstance(entry_time, str):
                    et = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                else:
                    et = entry_time
                elapsed = (datetime.now(timezone.utc) - et).total_seconds() / 60
                if elapsed >= self.max_hold_minutes:
                    return ExitSignal(
                        should_exit=True,
                        reason=f"Max hold time ({self.max_hold_minutes}min) exceeded",
                        exit_type="expiry",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.7,
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
            "avg_win_cents": float(self.take_profit),   # 6c
            "avg_loss_cents": float(self.stop_loss),     # 4c
        }
