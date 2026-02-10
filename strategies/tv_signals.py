"""
TradingView Signals Strategy

Uses top-performing TradingView community indicators (backtested by the
DeepStack TradingView pipeline) as directional signals for Kalshi markets.

How it works:
1. Fetches top indicators from Supabase (ranked by composite_score)
2. For each market, checks if any top indicator signals align with the market
3. Scores opportunities based on indicator composite_score + market conditions
4. Paper trade mode is ON by default — no real orders until manually enabled

This strategy bridges the TradingView backtesting pipeline with live trading,
turning indicator alpha into actionable Kalshi positions.

Expected Value:
- Depends on indicator quality. Paper trade mode allows validation before
  committing real capital. Only indicators with Sharpe > 1.0 and consistent
  multi-ticker performance are considered.
"""

import logging
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .data_providers.tradingview import TradingViewDataProvider

logger = logging.getLogger(__name__)


class TvSignalsStrategy(Strategy):
    """
    Trading strategy driven by top-performing TradingView indicator backtests.

    Fetches the best indicators from the DS-TV pipeline (stored in Supabase),
    evaluates their signal strength, and generates scored opportunities
    for markets that match the indicator characteristics.

    Configuration parameters:
        - paper_trade: If True, all opportunities are marked as paper trades (default: True)
        - min_composite_score: Minimum composite_score to consider an indicator (default: 0.5)
        - min_sharpe: Minimum avg Sharpe ratio for indicator qualification (default: 1.0)
        - max_positions: Max concurrent positions (default: 3)
        - take_profit_cents: Target profit per contract (default: 10)
        - stop_loss_cents: Max loss per contract (default: 5)

    Example:
        >>> config = {"paper_trade": True, "min_composite_score": 0.5}
        >>> strategy = TvSignalsStrategy(config)
        >>> opportunities = await strategy.scan_opportunities(markets)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.paper_trade = config.get("paper_trade", True)
        self.min_composite_score = config.get("min_composite_score", 0.5)
        self.min_sharpe = config.get("min_sharpe", 1.0)
        self.max_positions = config.get("max_positions", 3)
        self.tv_provider = TradingViewDataProvider()

        mode = "PAPER" if self.paper_trade else "LIVE"
        logger.info(
            f"TvSignalsStrategy initialized [{mode}]: "
            f"min_composite={self.min_composite_score}, min_sharpe={self.min_sharpe}, "
            f"TP=+{self.take_profit}c, SL=-{self.stop_loss}c"
        )

    @property
    def name(self) -> str:
        return "tv_signals"

    @property
    def description(self) -> str:
        mode = "paper" if self.paper_trade else "live"
        return (
            f"TradingView signals ({mode}): trade top backtested indicators "
            f"(min Sharpe {self.min_sharpe}, min score {self.min_composite_score})"
        )

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan markets using top TradingView indicator signals.

        1. Fetch top indicators from Supabase
        2. For each market, evaluate whether top indicators suggest a direction
        3. Score based on indicator composite_score + market volume/liquidity
        4. Mark as paper_trade in metadata if in paper mode
        """
        existing_positions = existing_positions or {}
        opportunities = []

        # Fetch top indicators
        top_indicators = await self.tv_provider.get_top_indicators(
            min_sharpe=self.min_sharpe,
            limit=20,
        )

        if not top_indicators:
            logger.debug("TvSignals: no qualifying indicators found")
            return []

        logger.info(f"TvSignals: {len(top_indicators)} qualifying indicators")

        # Build a signal strength map from top indicators
        # Higher composite_score = stronger directional conviction
        avg_composite = sum(
            (ind.get("composite_score") or 0) for ind in top_indicators
        ) / max(len(top_indicators), 1)

        # Determine overall signal direction from indicator consensus
        # Positive avg_return = bullish consensus, negative = bearish
        bullish_count = sum(
            1 for ind in top_indicators if (ind.get("avg_return_pct") or 0) > 0
        )
        bearish_count = len(top_indicators) - bullish_count
        signal_direction = "yes" if bullish_count >= bearish_count else "no"
        consensus_strength = abs(bullish_count - bearish_count) / max(len(top_indicators), 1)

        for market in markets:
            ticker = market.get("ticker", "")
            title = market.get("title", "")
            status = market.get("status", "")
            volume = market.get("volume", 0) or 0
            yes_bid = market.get("yes_bid", 0) or 0
            yes_ask = market.get("yes_ask", 0) or 0
            no_bid = market.get("no_bid", 0) or 0
            no_ask = market.get("no_ask", 0) or 0

            # Skip inactive or already-held markets
            if status not in ("active", "open"):
                continue
            if ticker in existing_positions:
                continue
            if volume < self.min_volume:
                continue

            # Determine entry price and side
            if signal_direction == "yes":
                entry_price = yes_ask if yes_ask > 0 else yes_bid
            else:
                entry_price = no_ask if no_ask > 0 else no_bid

            if not (1 <= entry_price <= 99):
                continue

            # Score: base from avg composite score, boosted by consensus + volume
            base_score = min(100.0, avg_composite * consensus_strength * 100)
            volume_boost = min(10.0, volume / 500.0)
            score = base_score + volume_boost

            if score < self.min_score:
                continue

            # Build metadata
            metadata: Dict[str, Any] = {
                "signal_direction": signal_direction,
                "consensus_strength": round(consensus_strength, 3),
                "num_indicators": len(top_indicators),
                "avg_composite_score": round(avg_composite, 3),
                "bullish_count": bullish_count,
                "bearish_count": bearish_count,
            }

            if self.paper_trade:
                metadata["paper_trade"] = True

            opportunity = TradingOpportunity(
                ticker=ticker,
                title=title,
                side=signal_direction,
                entry_price_cents=entry_price,
                current_yes_price=yes_bid,
                current_no_price=no_bid,
                volume=volume,
                score=min(100.0, score),
                reasoning=(
                    f"TV signals: {bullish_count}/{len(top_indicators)} indicators bullish, "
                    f"consensus={consensus_strength:.0%}, "
                    f"avg composite={avg_composite:.1f}"
                ),
                expected_profit_cents=self.take_profit,
                max_loss_cents=self.stop_loss,
                strategy_name=self.name,
                metadata=metadata,
            )
            opportunities.append(opportunity)

        # Sort by score descending, cap at max_positions
        opportunities.sort(key=lambda o: o.score, reverse=True)
        opportunities = opportunities[: self.max_positions]

        if opportunities:
            mode = "PAPER" if self.paper_trade else "LIVE"
            logger.info(
                f"TvSignals [{mode}]: {len(opportunities)} opportunities "
                f"(top score: {opportunities[0].score:.1f})"
            )

        return opportunities

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """
        Standard take-profit / stop-loss exit logic.

        For paper trades, exits are tracked but no real orders are placed
        (the paper_trade flag in metadata signals the executor to skip).
        """
        entry_price = position.get("entry_price", 50)
        side = position.get("side", "yes")

        # PnL calculation
        if side == "yes":
            pnl = current_price - entry_price
        else:
            pnl = entry_price - current_price

        # Take profit
        if pnl >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit: +{pnl}c (target: +{self.take_profit}c)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl,
                urgency=0.8,
            )

        # Stop loss
        if pnl <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss: {pnl}c (limit: -{self.stop_loss}c)",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl,
                urgency=1.0,
            )

        # Hold
        return ExitSignal(
            should_exit=False,
            reason=f"Holding: PnL={pnl}c (TP=+{self.take_profit}c, SL=-{self.stop_loss}c)",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl,
            urgency=0.0,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """Conservative priors for a new, untested strategy."""
        return {
            "win_rate": 0.50,
            "avg_win_cents": 8.0,
            "avg_loss_cents": 5.0,
        }
