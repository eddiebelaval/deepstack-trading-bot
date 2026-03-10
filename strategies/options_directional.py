"""
Options Directional Strategy (Buying Puts and Calls)

Buys puts when regime = trending_down, calls when regime = trending_up.
Unlike options_income (which SELLS puts for premium), this strategy takes
directional bets using options for leveraged exposure with capped downside.

Why buy options during a crisis:
    - Defined risk: max loss = premium paid (can't lose more than you put in)
    - Leverage: options amplify moves (a 3% stock move = 20-50% option move)
    - Capital efficient: control 100 shares for a fraction of the stock price
    - Both directions: buy puts to profit from drops, calls for rallies

Design:
    - Regime-gated: puts in trending_down, calls in trending_up
    - Targets ATM to slightly OTM options (10-20% OTM) with 14-45 DTE
    - Requires TV backtest consensus on the underlying (same data as stock_momentum)
    - Tighter take-profit (50% gain on premium) and stop-loss (40% loss)
    - Paper trading by default
    - Maximum 4 concurrent option positions
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import clamp_score

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


class OptionsDirectionalStrategy(Strategy):
    """
    Buy puts or calls based on regime direction + TV backtest conviction.

    Puts when market is falling, calls when it's rising. Uses options for
    leveraged exposure with defined maximum loss.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_sharpe = config.get("min_sharpe", 0.8)
        self.min_win_rate = config.get("min_win_rate", 55.0)
        self.min_strategies = config.get("min_strategies", 2)
        self.min_regime_confidence = config.get("min_regime_confidence", 0.45)
        self.target_dte_min = config.get("target_dte_min", 14)
        self.target_dte_max = config.get("target_dte_max", 45)
        self.otm_pct_max = config.get("otm_pct_max", 0.20)  # Max 20% OTM
        self.take_profit_pct = config.get("take_profit_pct", 0.50)  # 50% gain on premium
        self.stop_loss_pct = config.get("stop_loss_pct", 0.40)  # 40% loss on premium
        self.max_positions = config.get("max_positions", 4)
        self.paper_trade = config.get("paper_trade", True)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._signal_cache: Dict[str, Dict] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 300

    @property
    def name(self) -> str:
        return "options_directional"

    @property
    def description(self) -> str:
        return "Buy puts/calls based on regime direction + TV conviction"

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

    async def _fetch_signals(self) -> Dict[str, Dict]:
        """Fetch TV backtest signals for directional conviction."""
        now = datetime.now(timezone.utc)
        if (
            self._signal_cache
            and self._cache_time
            and (now - self._cache_time).total_seconds() < self._cache_ttl_seconds
        ):
            return self._signal_cache

        if not SUPABASE_URL or not SUPABASE_KEY:
            return {}

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/ds_tv_backtests",
                params={
                    "select": "ticker,script_name,sharpe_ratio,win_rate_pct,profit_factor",
                    "sharpe_ratio": f"gte.{self.min_sharpe}",
                    "win_rate_pct": f"gte.{self.min_win_rate}",
                    "order": "sharpe_ratio.desc",
                    "limit": "200",
                },
            )
            if resp.status_code != 200:
                return {}

            rows = resp.json()
            if not isinstance(rows, list):
                return {}

            ticker_signals: Dict[str, Dict] = {}
            for row in rows:
                ticker = row.get("ticker", "")
                if not ticker:
                    continue
                if ticker not in ticker_signals:
                    ticker_signals[ticker] = {
                        "ticker": ticker, "strategies": [], "count": 0,
                        "sharpe_sum": 0, "win_rate_sum": 0,
                    }
                sig = ticker_signals[ticker]
                sig["strategies"].append(row.get("script_name", ""))
                sig["sharpe_sum"] += row.get("sharpe_ratio", 0) or 0
                sig["win_rate_sum"] += row.get("win_rate_pct", 0) or 0
                sig["count"] += 1

            filtered = {}
            for t, s in ticker_signals.items():
                if s["count"] >= self.min_strategies:
                    n = s["count"]
                    s["avg_sharpe"] = s["sharpe_sum"] / n
                    s["avg_win_rate"] = s["win_rate_sum"] / n
                    filtered[t] = s

            self._signal_cache = filtered
            self._cache_time = now
            return filtered

        except Exception as e:
            logger.debug(f"Failed to fetch TV signals for options_directional: {e}")
            return {}

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
        governance_engine: Optional[Any] = None,
    ) -> List[TradingOpportunity]:
        """Scan for directional option opportunities.

        Buy puts in downtrends, calls in uptrends. Requires both regime
        confidence and TV backtest conviction on the underlying.
        """
        existing_positions = existing_positions or {}

        if not governance_engine:
            return []

        stock_regime = governance_engine.get_regime_for_asset_class("stock")
        if not stock_regime:
            return []

        if stock_regime.confidence < self.min_regime_confidence:
            return []

        regime_name = stock_regime.regime.value

        # Determine option type from regime
        if regime_name == "trending_down":
            target_right = "P"  # Buy puts
            direction = "bearish"
        elif regime_name == "trending_up":
            target_right = "C"  # Buy calls
            direction = "bullish"
        else:
            logger.debug("options_directional: regime %s — no directional signal", regime_name)
            return []

        signals = await self._fetch_signals()
        if not signals:
            return []

        opportunities = []
        for market in markets:
            if market.get("asset_class") != "option":
                continue

            underlying = market.get("underlying", "")
            if underlying not in signals:
                continue

            right = market.get("right", "")
            if right != target_right:
                continue

            ticker = market.get("ticker", "")
            if ticker in existing_positions:
                continue

            dte = market.get("dte", 0)
            if not (self.target_dte_min <= dte <= self.target_dte_max):
                continue

            underlying_price = market.get("underlying_price", 0)
            strike = market.get("strike", 0)
            if underlying_price <= 0 or strike <= 0:
                continue

            # OTM distance check
            if target_right == "P":
                otm_pct = (underlying_price / 100 - strike) / (underlying_price / 100)
            else:
                otm_pct = (strike - underlying_price / 100) / (underlying_price / 100)

            if otm_pct < 0 or otm_pct > self.otm_pct_max:
                continue

            premium = market.get("last_price", 0)
            if premium <= 0:
                continue

            signal = signals[underlying]
            score = clamp_score(
                stock_regime.confidence * 25 +
                signal["avg_sharpe"] * 15 +
                signal["avg_win_rate"] * 0.15 +
                min(signal["count"], 5) * 4 +
                (1 - otm_pct) * 15  # Closer to ATM = higher score
            )

            if score < self.min_score:
                continue

            expected_profit = int(premium * self.take_profit_pct)
            max_loss = int(premium * self.stop_loss_pct)

            right_label = "Put" if target_right == "P" else "Call"
            opportunities.append(TradingOpportunity(
                ticker=ticker,
                title=f"Buy {underlying} {strike}{right_label[0]} {market.get('expiry', '')} ({dte}d)",
                side="buy",
                entry_price_cents=premium,
                current_yes_price=premium,
                current_no_price=0,
                volume=market.get("volume", 0),
                score=score,
                reasoning=(
                    f"Direction: {direction} ({regime_name}, conf={stock_regime.confidence:.2f}) | "
                    f"TV consensus: {signal['count']} strategies | "
                    f"OTM: {otm_pct:.1%} | DTE: {dte} | "
                    f"Premium: ${premium/100:.2f}/share"
                ),
                expected_profit_cents=expected_profit,
                max_loss_cents=max_loss,
                strategy_name=self.name,
                asset_class="option",
                metadata={
                    "underlying": underlying,
                    "strike": strike,
                    "right": right,
                    "expiry": market.get("expiry", ""),
                    "dte": dte,
                    "otm_pct": otm_pct,
                    "direction": direction,
                    "underlying_price": underlying_price,
                    "tv_strategies": signal["strategies"][:5],
                    "tv_consensus_count": signal["count"],
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
        """Check if a bought option should be sold.

        For bought options: profit = current premium > entry premium.
        Tighter exits than stocks — time decay works against bought options.
        """
        entry_price = position.get("entry_price", position.get("entry_price_cents", 0))
        if entry_price <= 0:
            return ExitSignal(
                should_exit=False, reason="No entry price", exit_type="hold",
                current_price_cents=current_price, pnl_cents=0,
            )

        pnl_cents = current_price - entry_price
        pnl_pct = pnl_cents / entry_price if entry_price > 0 else 0

        # Take profit: premium gained target %
        if pnl_pct >= self.take_profit_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"Options TP: premium up {pnl_pct:.0%} (target {self.take_profit_pct:.0%})",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.8,
            )

        # Stop loss: premium decayed past threshold
        if pnl_pct <= -self.stop_loss_pct:
            return ExitSignal(
                should_exit=True,
                reason=f"Options SL: premium down {pnl_pct:.0%} (limit -{self.stop_loss_pct:.0%})",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        return ExitSignal(
            should_exit=False,
            reason=f"Holding option: premium {pnl_pct:+.0%}",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """Prior statistics for directional options strategy."""
        return {
            "win_rate": 0.40,        # Bought options expire worthless often
            "avg_win_cents": 600.0,  # ~$6 avg win (leveraged moves)
            "avg_loss_cents": 250.0, # ~$2.50 avg loss (premium paid, cut early)
        }
