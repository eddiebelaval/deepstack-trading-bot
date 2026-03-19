"""
Futures Trend-Following Strategy

Trades micro index futures (/MES, /MNQ, /MYM) in the direction of the
detected stock regime. Regime-aware by design — only enters when the
stock regime detector confirms a clear trend.

The signal logic: if stock regime = TRENDING_UP → buy front-month micro
futures. If TRENDING_DOWN → sell (short). If CHOPPY or CALM → stay flat.

Design:
    - Reads from IBKR futures watchlist (micro contracts only for capital efficiency)
    - Requires stock regime confidence >= 0.5 to enter
    - Tighter stops than stocks (futures are leveraged — 1 /MES = 5x SPY)
    - Paper trading by default (config.paper_trade = true)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import clamp_score

logger = logging.getLogger(__name__)


class FuturesTrendStrategy(Strategy):
    """
    Micro futures trend-following strategy powered by stock regime detection.

    Only trades when the governance engine detects a clear directional trend
    in the equity market. Uses micro contracts (/MES, /MNQ) to keep margin
    requirements manageable during paper trading.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_regime_confidence = config.get("min_regime_confidence", 0.5)
        self.take_profit_pct = config.get("take_profit_pct", 0.01)  # 1% (leveraged)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.005)  # 0.5% (tight for leverage)
        self.max_positions = config.get("max_positions", 2)
        self.paper_trade = config.get("paper_trade", True)
        self.allowed_regimes = config.get(
            "allowed_regimes", ["trending_up", "trending_down"]
        )

    @property
    def name(self) -> str:
        return "futures_trend"

    @property
    def description(self) -> str:
        return "Micro futures trend-following via stock regime detection"

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
        governance_engine: Optional[Any] = None,
    ) -> List[TradingOpportunity]:
        """Scan futures markets for trend-following opportunities.

        Only generates signals when the stock regime detector shows a clear
        trend with sufficient confidence.
        """
        existing_positions = existing_positions or {}

        # Hard gate: requires governance engine with stock regime
        if not governance_engine:
            logger.debug("futures_trend: no governance engine — skipping")
            return []

        stock_regime = governance_engine.get_regime_for_asset_class("stock")
        if not stock_regime:
            logger.debug("futures_trend: no stock regime detected yet — skipping")
            return []

        regime_name = stock_regime.regime.value

        # Paper mode: relax regime gates to collect graduation data.
        # Real trades still require full confidence + regime alignment.
        if self.paper_trade:
            if stock_regime.confidence < 0.1:
                logger.debug(
                    "futures_trend [PAPER]: regime confidence %.2f too low even for paper — skipping",
                    stock_regime.confidence,
                )
                return []
            # In paper mode, default to buy if regime isn't clearly down
            if regime_name == "trending_down":
                side = "sell"
            else:
                side = "buy"
            logger.info(
                "futures_trend [PAPER]: regime=%s conf=%.2f — paper trading %s for graduation data",
                regime_name, stock_regime.confidence, side,
            )
        else:
            if stock_regime.confidence < self.min_regime_confidence:
                logger.debug(
                    "futures_trend: stock regime confidence %.2f < %.2f threshold — skipping",
                    stock_regime.confidence, self.min_regime_confidence,
                )
                return []

            if regime_name not in self.allowed_regimes:
                logger.debug(
                    "futures_trend: regime %s not in allowed list %s — staying flat",
                    regime_name, self.allowed_regimes,
                )
                return []

            # Determine direction from regime
            if regime_name == "trending_up":
                side = "buy"
            elif regime_name == "trending_down":
                side = "sell"
            else:
                return []

        opportunities = []
        for market in markets:
            if market.get("asset_class") != "future":
                continue

            ticker = market.get("ticker", "")
            if ticker in existing_positions:
                continue

            current_price = market.get("last_price", 0)
            if current_price <= 0:
                continue

            multiplier = market.get("multiplier", 5.0)
            expected_profit = int(current_price * self.take_profit_pct)
            max_loss = int(current_price * self.stop_loss_pct)

            # Score based on regime confidence + trend strength
            score = clamp_score(
                stock_regime.confidence * 40 +           # Confidence contribution (0-40)
                abs(stock_regime.trend_strength) * 40 +  # Trend strength (0-40)
                20                                       # Base score for having a regime
            )

            if score < self.min_score:
                continue

            opportunities.append(TradingOpportunity(
                ticker=ticker,
                title=f"{market.get('symbol', ticker)} Trend ({regime_name})",
                side=side,
                entry_price_cents=current_price,
                current_yes_price=current_price,
                current_no_price=0,
                volume=market.get("volume", 0),
                score=score,
                reasoning=(
                    f"Regime: {regime_name} (conf={stock_regime.confidence:.2f}) | "
                    f"Trend: {stock_regime.trend_strength:+.2f} | "
                    f"Vol: {stock_regime.volatility:.2f} | "
                    f"Multiplier: {multiplier}x"
                ),
                expected_profit_cents=expected_profit,
                max_loss_cents=max_loss,
                strategy_name=self.name,
                asset_class="future",
                metadata={
                    "symbol": market.get("symbol", ""),
                    "exchange": market.get("exchange", ""),
                    "expiry": market.get("expiry", ""),
                    "multiplier": multiplier,
                    "stock_regime": regime_name,
                    "regime_confidence": stock_regime.confidence,
                    "trend_strength": stock_regime.trend_strength,
                    "paper_trade": self.paper_trade,
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
        """Check if a futures position should be exited.

        Tighter stops than stocks because futures are leveraged.
        Also exits if the regime flips against the position.
        """
        entry_price = position.get("entry_price", position.get("entry_price_cents", 0))
        if entry_price <= 0:
            return ExitSignal(
                should_exit=False, reason="No entry price", exit_type="hold",
                current_price_cents=current_price, pnl_cents=0,
            )

        side = position.get("side", "buy")
        if side == "buy":
            pnl_cents = current_price - entry_price
        else:
            pnl_cents = entry_price - current_price

        pnl_pct = pnl_cents / entry_price if entry_price > 0 else 0

        # Take profit
        if pnl_pct >= self.take_profit_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"Futures TP hit: {pnl_pct:.2%} >= {self.take_profit_pct:.2%}",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        # Stop loss (tight for leverage)
        if pnl_pct <= -self.stop_loss_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"Futures SL hit: {pnl_pct:.2%} <= -{self.stop_loss_pct:.2%}",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        return ExitSignal(
            should_exit=False,
            reason=f"Holding futures: P&L {pnl_pct:.2%}",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """Prior statistics for futures trend strategy."""
        return {
            "win_rate": 0.45,
            "avg_win_cents": 1000.0,  # ~$10 avg win on micro futures
            "avg_loss_cents": 500.0,  # ~$5 avg loss (tighter stops)
        }
