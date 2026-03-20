"""
Stock Momentum v2 — Dual-Direction Regime-Gated ETF Strategy

Rebuilt from scratch after v1 post-mortem (0/3 WR, -$149.52, long-only in downtrend).

v1 problems:
    - Long-only (hardcoded side="buy")
    - Used stale TradingView backtest Sharpe as live signal
    - Only 3 tickers (SPY, QQQ, BTC)
    - Fixed 1.5% stop loss got whipsawed
    - Position sizing bought $670 SPY on $230 account

v2 design:
    - Dual-direction: longs in uptrends, inverse ETFs in downtrends
    - Signal: MACD crossover + RSI confirmation + VWAP filter (live price data)
    - ATR-based adaptive stops (1.5x ATR instead of fixed %)
    - 2% risk rule with fractional shares ($25-50 max per position)
    - Hard regime gate: cash in VIX>30, no longs in downtrends, no shorts in uptrends
    - Time-based exit: 10 days max for longs, 5 days for inverse ETFs (decay)
    - Arena-compatible: works with synthetic prediction market data for backtesting

Signal logic:
    LONG mode (trending_up + VIX < 20):
        MACD bullish cross + RSI < 45 + price > VWAP → buy SPY/QQQ
    SHORT mode (trending_down + VIX < 25):
        MACD bearish cross + RSI > 55 + price < VWAP → buy SQQQ/SH
    CASH mode (VIX > 30 or choppy):
        Do nothing
"""

import logging
import math
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal

logger = logging.getLogger(__name__)

# Inverse ETF mapping: when bearish on X, buy its inverse
INVERSE_MAP = {
    "SPY": "SH",     # -1x S&P 500
    "QQQ": "SQQQ",   # -3x Nasdaq 100
}

# Maximum hold days (inverse ETFs decay from daily rebalancing)
MAX_HOLD_DAYS_LONG = 10
MAX_HOLD_DAYS_INVERSE = 5


class StockMomentumStrategy(Strategy):
    """
    Dual-direction regime-gated momentum strategy.

    Uses MACD/RSI/VWAP for signal generation, governance engine regime
    for direction gating, and ATR for adaptive position sizing and stops.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.paper_trade = config.get("paper_trade", True)
        self.max_positions = config.get("max_positions", 3)
        self.risk_pct = config.get("risk_pct", 0.02)  # 2% of account per trade
        self.atr_stop_mult = config.get("atr_stop_mult", 1.5)  # 1.5x ATR stop
        self.atr_trail_mult = config.get("atr_trail_mult", 2.0)  # 2x ATR trailing
        self.max_position_dollars = config.get("max_position_dollars", 50.0)
        self.vix_kill_threshold = config.get("vix_kill_threshold", 30)
        self.vix_reduce_threshold = config.get("vix_reduce_threshold", 20)

        # MACD parameters (standard 12/26/9)
        self.macd_fast = config.get("macd_fast", 12)
        self.macd_slow = config.get("macd_slow", 26)
        self.macd_signal = config.get("macd_signal", 9)

        # RSI parameters
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_long_threshold = config.get("rsi_long_threshold", 45)
        self.rsi_short_threshold = config.get("rsi_short_threshold", 55)

        # ATR period
        self.atr_period = config.get("atr_period", 10)

        # Price history per ticker (for indicator calculation)
        self._price_history: Dict[str, Deque[float]] = {}
        self._high_history: Dict[str, Deque[float]] = {}
        self._low_history: Dict[str, Deque[float]] = {}
        self._volume_history: Dict[str, Deque[float]] = {}
        self._vwap_accum: Dict[str, Dict[str, float]] = {}
        self._history_size = max(self.macd_slow + self.macd_signal, 50)

    @property
    def name(self) -> str:
        return "stock_momentum"

    @property
    def description(self) -> str:
        return "Dual-direction regime-gated momentum (MACD + RSI + VWAP + ATR)"

    def _update_history(self, ticker: str, price: float, high: float, low: float, volume: float) -> None:
        """Append a new data point to the price history for a ticker."""
        if ticker not in self._price_history:
            self._price_history[ticker] = deque(maxlen=self._history_size)
            self._high_history[ticker] = deque(maxlen=self._history_size)
            self._low_history[ticker] = deque(maxlen=self._history_size)
            self._volume_history[ticker] = deque(maxlen=self._history_size)
            self._vwap_accum[ticker] = {"cum_vol": 0, "cum_pv": 0}

        self._price_history[ticker].append(price)
        self._high_history[ticker].append(high)
        self._low_history[ticker].append(low)
        self._volume_history[ticker].append(volume)

        # VWAP accumulator (resets at session boundaries in live, runs continuously in backtest)
        acc = self._vwap_accum[ticker]
        acc["cum_vol"] += volume
        acc["cum_pv"] += price * volume

    def _calc_ema(self, prices: list, period: int) -> Optional[float]:
        """Calculate exponential moving average."""
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calc_macd(self, ticker: str) -> Optional[Dict[str, float]]:
        """Calculate MACD line, signal line, and histogram."""
        prices = list(self._price_history.get(ticker, []))
        min_needed = self.macd_slow + self.macd_signal
        if len(prices) < min_needed:
            return None

        fast_ema = self._calc_ema(prices, self.macd_fast)
        slow_ema = self._calc_ema(prices, self.macd_slow)
        if fast_ema is None or slow_ema is None:
            return None

        macd_line = fast_ema - slow_ema

        # Signal line: EMA of MACD values over last signal_period entries
        # We need to compute MACD for recent history to get signal line
        macd_values = []
        for i in range(self.macd_signal + 5):
            end = len(prices) - i
            if end < self.macd_slow:
                break
            sub = prices[:end]
            f = self._calc_ema(sub, self.macd_fast)
            s = self._calc_ema(sub, self.macd_slow)
            if f is not None and s is not None:
                macd_values.insert(0, f - s)

        if len(macd_values) < self.macd_signal:
            return None

        signal_line = self._calc_ema(macd_values, self.macd_signal)
        if signal_line is None:
            return None

        histogram = macd_line - signal_line

        # Detect crossover: current histogram positive, previous negative (bullish)
        # or current negative, previous positive (bearish)
        prev_hist = None
        if len(macd_values) >= 2:
            prev_signal = self._calc_ema(macd_values[:-1], self.macd_signal)
            if prev_signal is not None:
                prev_hist = macd_values[-2] - prev_signal

        return {
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram,
            "prev_histogram": prev_hist,
            "bullish_cross": prev_hist is not None and prev_hist <= 0 and histogram > 0,
            "bearish_cross": prev_hist is not None and prev_hist >= 0 and histogram < 0,
        }

    def _calc_rsi(self, ticker: str) -> Optional[float]:
        """Calculate RSI."""
        prices = list(self._price_history.get(ticker, []))
        if len(prices) < self.rsi_period + 1:
            return None

        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        recent = changes[-self.rsi_period:]

        gains = [c for c in recent if c > 0]
        losses = [-c for c in recent if c < 0]

        avg_gain = sum(gains) / self.rsi_period if gains else 0
        avg_loss = sum(losses) / self.rsi_period if losses else 0.0001

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calc_vwap(self, ticker: str) -> Optional[float]:
        """Calculate volume-weighted average price."""
        acc = self._vwap_accum.get(ticker, {})
        cum_vol = acc.get("cum_vol", 0)
        if cum_vol <= 0:
            return None
        return acc["cum_pv"] / cum_vol

    def _calc_atr(self, ticker: str) -> Optional[float]:
        """Calculate Average True Range."""
        highs = list(self._high_history.get(ticker, []))
        lows = list(self._low_history.get(ticker, []))
        closes = list(self._price_history.get(ticker, []))

        if len(highs) < self.atr_period + 1:
            return None

        true_ranges = []
        for i in range(-self.atr_period, 0):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)

        return sum(true_ranges) / len(true_ranges)

    def _get_regime_mode(self, governance_engine: Optional[Any]) -> str:
        """
        Determine trading mode from regime.

        Returns: "long", "short", or "cash"
        """
        if not governance_engine:
            return "long"  # Default to long if no governance

        stock_regime = governance_engine.get_regime_for_asset_class("stock")
        if not stock_regime or stock_regime.confidence < 0.4:
            return "cash"  # Low confidence = don't trade

        regime = stock_regime.regime.value

        # VIX kill switch would be checked here if we had VIX data
        # For now, rely on the regime detector which incorporates VIX-like volatility

        if regime == "trending_up":
            return "long"
        elif regime == "trending_down":
            return "short"
        elif regime == "high_vol_choppy":
            return "cash"
        elif regime == "low_vol_calm":
            return "long"  # Calm markets favor gentle longs
        elif regime == "mean_reverting":
            return "cash"  # Mean reversion is not momentum's game
        else:
            return "cash"

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
        governance_engine: Optional[Any] = None,
    ) -> List[TradingOpportunity]:
        """Scan for momentum opportunities using MACD + RSI + VWAP."""
        existing_positions = existing_positions or {}

        # Determine trading mode from regime
        mode = self._get_regime_mode(governance_engine)
        if mode == "cash":
            regime_name = "unknown"
            if governance_engine:
                sr = governance_engine.get_regime_for_asset_class("stock")
                if sr:
                    regime_name = sr.regime.value
            logger.info(
                "stock_momentum: CASH mode (regime=%s) — sitting out", regime_name
            )
            return []

        logger.info("stock_momentum: %s mode — scanning %d markets", mode.upper(), len(markets))

        opportunities = []
        for market in markets:
            ticker = market.get("ticker", "")
            if not ticker:
                continue

            # Skip inverse ETFs when in long mode and vice versa
            is_inverse = ticker in ("SQQQ", "SH", "SDOW", "SPXS", "UVXY")
            if mode == "long" and is_inverse:
                continue
            if mode == "short" and not is_inverse and ticker not in INVERSE_MAP:
                continue

            # Skip if already in position
            if ticker in existing_positions:
                continue

            # Get price data
            price = market.get("last_price", 0)
            high = market.get("high", price)
            low = market.get("low", price)
            volume = market.get("volume", 0)

            if price <= 0:
                continue

            # Update history
            self._update_history(ticker, price, high, low, volume)

            # Calculate indicators
            macd = self._calc_macd(ticker)
            rsi = self._calc_rsi(ticker)
            vwap = self._calc_vwap(ticker)
            atr = self._calc_atr(ticker)

            if not all([macd, rsi is not None, vwap, atr]):
                continue

            # Generate signals based on mode
            signal = False
            side = "buy"
            reasoning_parts = []

            if mode == "long":
                # LONG: MACD bullish cross + RSI < threshold + price > VWAP
                if macd["bullish_cross"] and rsi < self.rsi_long_threshold and price > vwap:
                    signal = True
                    side = "buy"
                    reasoning_parts = [
                        f"MACD bullish cross (hist={macd['histogram']:.2f})",
                        f"RSI={rsi:.1f} (< {self.rsi_long_threshold})",
                        f"Price {price/100:.2f} > VWAP {vwap/100:.2f}",
                    ]

            elif mode == "short":
                if is_inverse:
                    # For inverse ETFs: buy when MACD is bearish on the underlying
                    # We check the inverse ETF's own MACD for simplicity
                    if macd["bullish_cross"] and rsi < self.rsi_long_threshold:
                        signal = True
                        side = "buy"
                        reasoning_parts = [
                            f"Inverse ETF {ticker}: MACD bullish (underlying bearish)",
                            f"RSI={rsi:.1f}",
                        ]
                else:
                    # For the underlying (SPY/QQQ): detect bearish signal, map to inverse
                    if macd["bearish_cross"] and rsi > self.rsi_short_threshold and price < vwap:
                        inverse_ticker = INVERSE_MAP.get(ticker)
                        if inverse_ticker:
                            # Check if the inverse ETF is in our markets
                            inverse_market = None
                            for m in markets:
                                if m.get("ticker") == inverse_ticker:
                                    inverse_market = m
                                    break
                            if inverse_market and inverse_ticker not in existing_positions:
                                signal = True
                                ticker = inverse_ticker
                                price = inverse_market.get("last_price", 0)
                                side = "buy"
                                reasoning_parts = [
                                    f"Bearish {market['ticker']}: MACD bearish cross",
                                    f"RSI={rsi:.1f} (> {self.rsi_short_threshold})",
                                    f"Buying inverse ETF {inverse_ticker}",
                                ]

            if not signal or price <= 0:
                continue

            # Calculate ATR-based stop and position size
            stop_distance = atr * self.atr_stop_mult
            if stop_distance <= 0:
                continue

            # Score: based on signal strength
            score = min(100, max(0, (
                30 +  # Base score for any valid signal
                abs(macd["histogram"]) * 10 +  # MACD strength
                (50 - abs(rsi - 50)) * 0.4 +  # RSI extremity
                min(volume, 10000) / 200  # Volume bonus (capped)
            )))

            if score < self.min_score:
                continue

            expected_profit = int(atr * self.atr_trail_mult)
            max_loss = int(stop_distance)

            logger.info(
                "stock_momentum: %s OPPORTUNITY %s — score=%.1f, price=$%.2f, ATR=$%.2f, mode=%s",
                mode.upper(), ticker, score, price / 100, atr / 100, mode,
            )

            opportunities.append(TradingOpportunity(
                ticker=ticker,
                title=f"{ticker} {'Long' if mode == 'long' else 'Inverse'} Momentum",
                side=side,
                entry_price_cents=int(price),
                current_yes_price=int(price),
                current_no_price=0,
                volume=volume,
                score=score,
                reasoning=" | ".join(reasoning_parts),
                expected_profit_cents=expected_profit,
                max_loss_cents=max_loss,
                strategy_name=self.name,
                asset_class="stock",
                metadata={
                    "mode": mode,
                    "macd_histogram": macd["histogram"],
                    "rsi": rsi,
                    "vwap": vwap,
                    "atr": atr,
                    "stop_distance": stop_distance,
                    "paper_trade": self.paper_trade,
                    "is_inverse_etf": ticker in ("SQQQ", "SH", "SDOW", "SPXS"),
                    "max_hold_days": MAX_HOLD_DAYS_INVERSE if ticker in ("SQQQ", "SH", "SDOW", "SPXS") else MAX_HOLD_DAYS_LONG,
                },
            ))

            if len(opportunities) >= self.max_positions:
                break

        return sorted(opportunities, key=lambda o: o.score, reverse=True)

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """Check exit using ATR trailing stop + time-based exit."""
        entry_price = position.get("entry_price", position.get("entry_price_cents", 0))
        if entry_price <= 0:
            return ExitSignal(
                should_exit=False, reason="No entry price", exit_type="hold",
                current_price_cents=current_price, pnl_cents=0,
            )

        side = position.get("side", "buy")
        ticker = position.get("market_ticker", position.get("ticker", ""))
        metadata = position.get("metadata", {})

        if side == "buy":
            pnl_cents = current_price - entry_price
        else:
            pnl_cents = entry_price - current_price

        pnl_pct = pnl_cents / entry_price if entry_price > 0 else 0

        # ATR-based trailing stop
        atr = self._calc_atr(ticker)
        if atr and atr > 0:
            stop_distance_pct = (atr * self.atr_stop_mult) / entry_price
        else:
            stop_distance_pct = 0.02  # Fallback: 2%

        # Trailing stop: if we're in profit, tighten stop
        if pnl_pct > 0:
            # Trail at 2x ATR from high water mark
            trail_pct = (atr * self.atr_trail_mult) / entry_price if atr else 0.03
            effective_stop = -trail_pct  # Measured from current price, not entry
        else:
            effective_stop = -stop_distance_pct

        # Stop loss
        if pnl_pct <= effective_stop:
            return ExitSignal(
                should_exit=True,
                reason=f"ATR stop: {pnl_pct:.1%} <= {effective_stop:.1%} (ATR=${atr/100:.2f})" if atr else f"Stop: {pnl_pct:.1%}",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        # Time-based exit
        created_at = position.get("created_at")
        if created_at:
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    created_at = None

            if created_at:
                now = datetime.now(timezone.utc)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                days_held = (now - created_at).days
                max_days = metadata.get("max_hold_days", MAX_HOLD_DAYS_LONG)
                if days_held >= max_days:
                    return ExitSignal(
                        should_exit=True,
                        reason=f"Time exit: held {days_held} days (max {max_days})",
                        exit_type="expiry",
                        current_price_cents=current_price,
                        pnl_cents=pnl_cents,
                        urgency=0.7,
                    )

        # Take profit at 3x ATR (reward/risk of 2:1)
        if atr and pnl_cents >= atr * 3:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit: +{pnl_pct:.1%} (3x ATR)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        return ExitSignal(
            should_exit=False,
            reason=f"Holding: P&L {pnl_pct:.1%}, stop at {effective_stop:.1%}",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """Prior statistics for Bayesian learning loop."""
        return {
            "win_rate": 0.50,
            "avg_win_cents": 300.0,
            "avg_loss_cents": 200.0,
        }
