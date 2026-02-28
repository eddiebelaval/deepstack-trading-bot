"""
Stock Momentum Strategy

Reads TradingView-validated stock signals from the Supabase scoreboard
(populated by the DeepStack TradingView integration). Generates buy/sell
signals for stocks with strong momentum characteristics.

Design:
    - Reads from ds_tv_strategy_scores (existing table from TV integration)
    - Filters for Sharpe > min_sharpe (default 1.0)
    - Uses composite score from TV validation as opportunity score
    - Paper trading by default (config.paper_trade = true)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import Strategy, TradingOpportunity, ExitSignal

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


class StockMomentumStrategy(Strategy):
    """
    Stock momentum strategy powered by TradingView scoreboard signals.

    Reads validated strategies from Supabase (ds_tv_strategy_scores table),
    filters by Sharpe ratio and composite score, generates stock trading
    opportunities.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_sharpe = config.get("min_sharpe", 1.0)
        self.take_profit_pct = config.get("take_profit_pct", 0.03)  # 3%
        self.stop_loss_pct = config.get("stop_loss_pct", 0.015)  # 1.5%
        self.max_positions = config.get("max_positions", 5)
        self.paper_trade = config.get("paper_trade", True)
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "stock_momentum"

    @property
    def description(self) -> str:
        return "Stock momentum signals from TradingView-validated strategies"

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._http_client:
            self._http_client = httpx.AsyncClient(
                timeout=10.0,
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                },
            )
        return self._http_client

    async def _fetch_tv_signals(self) -> List[Dict]:
        """Fetch validated strategy signals from TradingView scoreboard."""
        if not SUPABASE_URL or not SUPABASE_KEY:
            logger.debug("Supabase not configured for TV signals")
            return []

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/ds_tv_strategy_scores",
                params={
                    "select": "ticker,strategy_name,sharpe_ratio,composite_score,win_rate,total_trades,net_profit_pct,signal,updated_at",
                    "sharpe_ratio": f"gte.{self.min_sharpe}",
                    "order": "composite_score.desc",
                    "limit": "20",
                },
            )
            if resp.status_code == 200:
                return resp.json()
            logger.debug(f"TV signals fetch returned {resp.status_code}")
            return []
        except Exception as e:
            logger.debug(f"Failed to fetch TV signals: {e}")
            return []

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """Scan TradingView scoreboard for stock momentum opportunities."""
        existing_positions = existing_positions or {}
        signals = await self._fetch_tv_signals()

        if not signals:
            return []

        opportunities = []
        for signal in signals:
            ticker = signal.get("ticker", "")
            if not ticker or ticker in existing_positions:
                continue

            composite_score = signal.get("composite_score", 0)
            if composite_score < self.min_score:
                continue

            # Determine side from TV signal
            tv_signal = signal.get("signal", "neutral")
            if tv_signal in ("strong_buy", "buy"):
                side = "buy"
            elif tv_signal in ("strong_sell", "sell"):
                side = "sell"
            else:
                continue  # Skip neutral signals

            # Find matching market data from the IBKR watchlist
            market_data = None
            for m in markets:
                if m.get("ticker") == ticker:
                    market_data = m
                    break

            if not market_data:
                continue

            current_price = market_data.get("last_price", 0)
            if current_price <= 0:
                continue

            # Calculate expected profit/loss based on percentage targets
            expected_profit = int(current_price * self.take_profit_pct)
            max_loss = int(current_price * self.stop_loss_pct)

            # Scale composite_score (0-1) to opportunity score (0-100)
            score = min(100, composite_score * 100)

            opportunities.append(TradingOpportunity(
                ticker=ticker,
                title=f"{ticker} Momentum ({tv_signal})",
                side=side,
                entry_price_cents=current_price,
                current_yes_price=current_price,
                current_no_price=0,
                volume=market_data.get("volume", 0),
                score=score,
                reasoning=(
                    f"TV signal: {tv_signal} | "
                    f"Sharpe: {signal.get('sharpe_ratio', 0):.2f} | "
                    f"Win rate: {signal.get('win_rate', 0):.1%} | "
                    f"Net profit: {signal.get('net_profit_pct', 0):.1f}%"
                ),
                expected_profit_cents=expected_profit,
                max_loss_cents=max_loss,
                strategy_name=self.name,
                asset_class="stock",
                metadata={
                    "tv_strategy": signal.get("strategy_name"),
                    "sharpe_ratio": signal.get("sharpe_ratio"),
                    "composite_score": composite_score,
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
        """Check if a stock position should be exited."""
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
                reason=f"Take profit hit: {pnl_pct:.1%} >= {self.take_profit_pct:.1%}",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        # Stop loss
        if pnl_pct <= -self.stop_loss_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss hit: {pnl_pct:.1%} <= -{self.stop_loss_pct:.1%}",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        return ExitSignal(
            should_exit=False,
            reason=f"Holding: P&L {pnl_pct:.1%}",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """Prior statistics for stock momentum strategy."""
        return {
            "win_rate": 0.55,
            "avg_win_cents": 500.0,  # $5 avg win on stock trades
            "avg_loss_cents": 300.0,  # $3 avg loss
        }
