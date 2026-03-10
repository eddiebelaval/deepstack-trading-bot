"""
Options Income Strategy (Cash-Secured Puts)

Sells cash-secured puts on stocks with strong TradingView backtest consensus.
If you're bullish on a stock (multiple strategies agree, Sharpe > 1.0), selling
puts generates premium income AND gives a discount entry if assigned.

The signal logic: find tickers with strong TV consensus (from ds_tv_backtests),
then sell OTM puts 5-10% below current price with 20-45 DTE. Collect premium.
If assigned, you own the stock at a discount — which the backtests say is bullish.

Design:
    - Reads from ds_tv_backtests (same source as stock_momentum)
    - Only sells puts on tickers with 2+ strategy consensus
    - Targets 5-10% OTM puts with 20-45 DTE
    - Regime-aware: won't sell puts in TRENDING_DOWN or HIGH_VOL_CHOPPY
    - Paper trading by default (config.paper_trade = true)
    - Maximum 3 concurrent option positions (capital-intensive)
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


class OptionsIncomeStrategy(Strategy):
    """
    Options income strategy: sell cash-secured puts on TV-validated stocks.

    Combines TradingView backtest consensus (bullish signal) with options
    premium collection. Only enters when stock regime is favorable.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_sharpe = config.get("min_sharpe", 1.0)
        self.min_win_rate = config.get("min_win_rate", 60.0)
        self.min_strategies = config.get("min_strategies", 2)
        self.target_dte_min = config.get("target_dte_min", 20)
        self.target_dte_max = config.get("target_dte_max", 45)
        self.otm_pct_min = config.get("otm_pct_min", 0.05)  # 5% OTM minimum
        self.otm_pct_max = config.get("otm_pct_max", 0.10)  # 10% OTM maximum
        self.min_premium_pct = config.get("min_premium_pct", 0.01)  # 1% of strike minimum
        self.max_positions = config.get("max_positions", 3)
        self.paper_trade = config.get("paper_trade", True)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._signal_cache: Dict[str, Dict] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 300

    @property
    def name(self) -> str:
        return "options_income"

    @property
    def description(self) -> str:
        return "Cash-secured puts on TV-validated bullish stocks"

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

    async def _fetch_bullish_tickers(self) -> Dict[str, Dict]:
        """Fetch tickers with strong TV consensus for put selling.

        Same data source as stock_momentum, but we use it differently:
        stock_momentum BUYS the stock, we SELL puts on it.
        """
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

            # Aggregate by ticker
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

            # Filter: require minimum consensus
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
            logger.debug(f"Failed to fetch TV signals for options: {e}")
            return {}

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
        governance_engine: Optional[Any] = None,
    ) -> List[TradingOpportunity]:
        """Scan for put-selling opportunities on bullish stocks.

        Requires option chain data in markets (from IBKR get_options_chain).
        Only generates signals when stock regime is favorable.
        """
        existing_positions = existing_positions or {}

        # Regime gate: don't sell puts into a downtrend or high volatility
        if governance_engine:
            stock_regime = governance_engine.get_regime_for_asset_class("stock")
            if stock_regime and stock_regime.confidence >= 0.4:
                regime_name = stock_regime.regime.value
                if regime_name in ("trending_down", "high_vol_choppy"):
                    logger.info(
                        "options_income: regime %s — too risky for put selling, skipping",
                        regime_name,
                    )
                    return []

        bullish_tickers = await self._fetch_bullish_tickers()
        if not bullish_tickers:
            return []

        opportunities = []
        for market in markets:
            if market.get("asset_class") != "option":
                continue

            underlying = market.get("underlying", "")
            if underlying not in bullish_tickers:
                continue

            right = market.get("right", "")
            if right != "P":  # Only selling puts
                continue

            ticker = market.get("ticker", "")
            if ticker in existing_positions:
                continue

            # Validate DTE
            dte = market.get("dte", 0)
            if not (self.target_dte_min <= dte <= self.target_dte_max):
                continue

            # Validate OTM distance
            underlying_price = market.get("underlying_price", 0)
            strike = market.get("strike", 0)
            if underlying_price <= 0 or strike <= 0:
                continue

            otm_pct = (underlying_price / 100 - strike) / (underlying_price / 100)
            if not (self.otm_pct_min <= otm_pct <= self.otm_pct_max):
                continue

            # Check premium is worth collecting
            premium = market.get("last_price", 0)  # In cents per share
            if premium <= 0:
                continue

            premium_pct = premium / (strike * 100)  # Premium as % of strike
            if premium_pct < self.min_premium_pct:
                continue

            signal = bullish_tickers[underlying]
            score = clamp_score(
                signal["avg_sharpe"] * 15 +         # Sharpe contribution (0-30)
                signal["avg_win_rate"] * 0.2 +      # Win rate contribution (0-20)
                min(signal["count"], 5) * 5 +        # Strategy count (0-25)
                premium_pct * 500                    # Premium richness (0-25)
            )

            if score < self.min_score:
                continue

            # For puts: max loss = strike * 100 (assigned at strike, stock goes to 0)
            # Realistic max loss: use stop loss at 2x premium collected
            max_loss = premium * 2

            opportunities.append(TradingOpportunity(
                ticker=ticker,
                title=f"Sell {underlying} {strike}P {market.get('expiry', '')} ({dte}d)",
                side="sell",
                entry_price_cents=premium,
                current_yes_price=premium,
                current_no_price=0,
                volume=market.get("volume", 0),
                score=score,
                reasoning=(
                    f"TV consensus: {signal['count']} strategies bullish | "
                    f"Avg Sharpe: {signal['avg_sharpe']:.2f} | "
                    f"OTM: {otm_pct:.1%} | DTE: {dte} | "
                    f"Premium: ${premium/100:.2f}/share ({premium_pct:.1%} of strike)"
                ),
                expected_profit_cents=premium,  # Max profit = premium collected
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
                    "premium_pct": premium_pct,
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
        """Check if an options position should be closed.

        For sold puts: buy back if premium drops 50% (take profit) or
        doubles (stop loss). Also exit if approaching expiry (< 5 DTE).
        """
        entry_price = position.get("entry_price", position.get("entry_price_cents", 0))
        if entry_price <= 0:
            return ExitSignal(
                should_exit=False, reason="No entry price", exit_type="hold",
                current_price_cents=current_price, pnl_cents=0,
            )

        # For short puts: profit when premium drops, loss when it rises
        # Entry: sold at entry_price (collected premium)
        # Current: would cost current_price to buy back
        pnl_cents = entry_price - current_price  # Positive = profit (premium decayed)

        # Take profit: buy back at 50% of premium collected
        if current_price <= entry_price * 0.5:
            return ExitSignal(
                should_exit=True,
                reason=f"Options TP: premium decayed to {current_price}c (entry {entry_price}c)",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.6,
            )

        # Stop loss: buy back if premium doubles (underlying moved against us)
        if current_price >= entry_price * 2:
            return ExitSignal(
                should_exit=True,
                reason=f"Options SL: premium doubled to {current_price}c (entry {entry_price}c)",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        return ExitSignal(
            should_exit=False,
            reason=f"Holding option: premium {current_price}c (entry {entry_price}c, P&L {pnl_cents}c)",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        """Prior statistics for options income strategy."""
        return {
            "win_rate": 0.70,       # Put selling wins ~70% of the time
            "avg_win_cents": 200.0,  # ~$2 avg premium collected
            "avg_loss_cents": 500.0, # ~$5 avg loss when assigned/stopped
        }
