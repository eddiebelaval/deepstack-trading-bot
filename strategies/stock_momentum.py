"""
Stock Momentum Strategy

Reads TradingView-validated backtest results from Supabase (ds_tv_backtests)
to identify high-conviction stock trading opportunities. Filters by Sharpe,
win rate, and trade count to find strategies with proven edge.

The signal logic: if a backtested strategy has Sharpe > 1.0 and win rate > 60%
on a given ticker, we treat that as a BUY signal for that ticker. The strength
of the signal (opportunity score) combines Sharpe, win rate, and profit factor.

Design:
    - Reads from ds_tv_backtests (1,400+ scored results)
    - Filters: Sharpe >= min_sharpe, win_rate >= min_win_rate, num_trades >= min_trades
    - Aggregates multiple strategy signals per ticker (consensus scoring)
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
    Stock momentum strategy powered by TradingView backtest results.

    Reads validated backtests from Supabase (ds_tv_backtests table),
    aggregates signals per ticker, and generates stock trading opportunities
    for tickers with strong consensus across multiple strategies.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_sharpe = config.get("min_sharpe", 1.0)
        self.min_win_rate = config.get("min_win_rate", 60.0)
        self.min_trades = config.get("min_trades", 5)
        self.min_strategies = config.get("min_strategies", 2)
        self.take_profit_pct = config.get("take_profit_pct", 0.03)  # 3%
        self.stop_loss_pct = config.get("stop_loss_pct", 0.015)  # 1.5%
        self.max_positions = config.get("max_positions", 5)
        self.paper_trade = config.get("paper_trade", True)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._signal_cache: Dict[str, Dict] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # Refresh signals every 5 min

    @property
    def name(self) -> str:
        return "stock_momentum"

    @property
    def description(self) -> str:
        return "Stock momentum signals from TradingView-validated backtests"

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

    async def _fetch_tv_signals(self) -> Dict[str, Dict]:
        """
        Fetch and aggregate backtest results into per-ticker signals.

        Returns dict of ticker -> signal data with consensus scoring.
        """
        # Use cache if fresh
        now = datetime.now(timezone.utc)
        if (
            self._signal_cache
            and self._cache_time
            and (now - self._cache_time).total_seconds() < self._cache_ttl_seconds
        ):
            return self._signal_cache

        if not SUPABASE_URL or not SUPABASE_KEY:
            logger.debug("Supabase not configured for TV signals")
            return {}

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/ds_tv_backtests",
                params={
                    "select": "ticker,script_name,sharpe_ratio,win_rate_pct,profit_factor,roi_pct,num_trades",
                    "sharpe_ratio": f"gte.{self.min_sharpe}",
                    "win_rate_pct": f"gte.{self.min_win_rate}",
                    "num_trades": f"gte.{self.min_trades}",
                    "order": "sharpe_ratio.desc",
                    "limit": "200",
                },
            )
            if resp.status_code != 200:
                logger.debug(f"TV backtests fetch returned {resp.status_code}")
                return {}

            rows = resp.json()
            if not isinstance(rows, list):
                return {}

            # Aggregate by ticker: count strategies, average metrics
            ticker_signals: Dict[str, Dict] = {}
            for row in rows:
                ticker = row.get("ticker", "")
                if not ticker:
                    continue

                if ticker not in ticker_signals:
                    ticker_signals[ticker] = {
                        "ticker": ticker,
                        "strategies": [],
                        "sharpe_sum": 0,
                        "win_rate_sum": 0,
                        "roi_sum": 0,
                        "profit_factor_sum": 0,
                        "count": 0,
                    }

                sig = ticker_signals[ticker]
                sig["strategies"].append(row.get("script_name", ""))
                sig["sharpe_sum"] += row.get("sharpe_ratio", 0) or 0
                sig["win_rate_sum"] += row.get("win_rate_pct", 0) or 0
                sig["roi_sum"] += row.get("roi_pct", 0) or 0
                sig["profit_factor_sum"] += row.get("profit_factor", 0) or 0
                sig["count"] += 1

            # Compute averages and consensus score
            for ticker, sig in ticker_signals.items():
                n = sig["count"]
                sig["avg_sharpe"] = sig["sharpe_sum"] / n
                sig["avg_win_rate"] = sig["win_rate_sum"] / n
                sig["avg_roi"] = sig["roi_sum"] / n
                sig["avg_profit_factor"] = sig["profit_factor_sum"] / n
                # Consensus score: more strategies agreeing = stronger signal
                sig["consensus_score"] = min(100, (
                    sig["avg_sharpe"] * 20 +        # Sharpe contribution (0-40)
                    sig["avg_win_rate"] * 0.3 +     # Win rate contribution (0-30)
                    min(n, 5) * 6                    # Strategy count bonus (0-30)
                ))

            # Filter: require minimum strategy consensus
            filtered = {
                t: s for t, s in ticker_signals.items()
                if s["count"] >= self.min_strategies
            }

            self._signal_cache = filtered
            self._cache_time = now
            logger.info(
                f"TV signals refreshed: {len(rows)} backtests -> "
                f"{len(filtered)} tickers with {self.min_strategies}+ strategy consensus"
            )
            return filtered

        except Exception as e:
            logger.debug(f"Failed to fetch TV signals: {e}")
            return {}

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
        governance_engine: Optional[Any] = None,
    ) -> List[TradingOpportunity]:
        """Scan TradingView backtests for stock momentum opportunities.

        Args:
            markets: IBKR market data dicts.
            existing_positions: Currently open positions to avoid doubling up.
            governance_engine: GovernanceEngine instance for regime awareness.
                If the stock regime is HIGH_VOL_CHOPPY or TRENDING_DOWN,
                we reduce position count and raise the score threshold.
        """
        existing_positions = existing_positions or {}

        # Regime-aware gating: check stock market conditions before scanning
        regime_penalty = 0
        max_positions = self.max_positions
        stock_regime = None
        if governance_engine:
            stock_regime = governance_engine.get_regime_for_asset_class("stock")
            if stock_regime and stock_regime.confidence >= 0.4:
                regime_name = stock_regime.regime.value
                if regime_name == "high_vol_choppy":
                    # High volatility + no trend = dangerous for momentum
                    regime_penalty = 20
                    max_positions = max(1, self.max_positions // 2)
                    logger.info(
                        "stock_momentum: HIGH_VOL_CHOPPY regime detected "
                        "(conf=%.2f) — raising score threshold +20, "
                        "halving max positions to %d",
                        stock_regime.confidence, max_positions,
                    )
                elif regime_name == "trending_down":
                    # Downtrend = momentum buy signals are counter-trend
                    regime_penalty = 30
                    max_positions = max(1, self.max_positions // 3)
                    logger.info(
                        "stock_momentum: TRENDING_DOWN regime detected "
                        "(conf=%.2f) — raising score threshold +30, "
                        "reducing max positions to %d",
                        stock_regime.confidence, max_positions,
                    )
                elif regime_name == "trending_up":
                    # Uptrend = momentum buy signals are WITH the trend
                    regime_penalty = -5  # Slight bonus
                    logger.info(
                        "stock_momentum: TRENDING_UP regime detected "
                        "(conf=%.2f) — favorable conditions",
                        stock_regime.confidence,
                    )

        signals = await self._fetch_tv_signals()

        if not signals:
            logger.info("stock_momentum: no TV signals available — skipping scan")
            return []

        available_tickers = [m.get("ticker") for m in markets]
        logger.info(
            "stock_momentum: %d TV signals, %d IBKR markets available (%s)",
            len(signals), len(markets),
            ", ".join(available_tickers[:8]) if available_tickers else "NONE",
        )

        opportunities = []
        for ticker, signal in signals.items():
            if ticker in existing_positions:
                logger.info("stock_momentum: %s — already in position, skipping", ticker)
                continue

            # Find matching market data from IBKR
            market_data = None
            for m in markets:
                if m.get("ticker") == ticker:
                    market_data = m
                    break

            if not market_data:
                logger.info("stock_momentum: %s — no IBKR market data match, skipping", ticker)
                continue

            current_price = market_data.get("last_price", 0)
            if current_price <= 0:
                logger.info("stock_momentum: %s — price is %s, skipping", ticker, current_price)
                continue

            # All backtested strategies with high Sharpe + win rate = BUY signal
            side = "buy"

            # Calculate expected profit/loss based on percentage targets
            expected_profit = int(current_price * self.take_profit_pct)
            max_loss = int(current_price * self.stop_loss_pct)

            score = signal["consensus_score"]
            adjusted_min_score = self.min_score + regime_penalty
            if score < adjusted_min_score:
                logger.info("stock_momentum: %s — score %.1f < min %.1f, skipping", ticker, score, adjusted_min_score)
                continue

            logger.info(
                "stock_momentum: OPPORTUNITY %s — score=%.1f, price=$%.2f, %d strategies",
                ticker, score, current_price / 100, signal["count"],
            )
            opportunities.append(TradingOpportunity(
                ticker=ticker,
                title=f"{ticker} Momentum ({signal['count']} strategies)",
                side=side,
                entry_price_cents=current_price,
                current_yes_price=current_price,
                current_no_price=0,
                volume=market_data.get("volume", 0),
                score=score,
                reasoning=(
                    f"TV consensus: {signal['count']} strategies | "
                    f"Avg Sharpe: {signal['avg_sharpe']:.2f} | "
                    f"Avg WR: {signal['avg_win_rate']:.1f}% | "
                    f"Avg ROI: {signal['avg_roi']:.1f}% | "
                    f"Avg PF: {signal['avg_profit_factor']:.2f}"
                ),
                expected_profit_cents=expected_profit,
                max_loss_cents=max_loss,
                strategy_name=self.name,
                asset_class="stock",
                metadata={
                    "tv_strategies": signal["strategies"][:5],
                    "avg_sharpe": signal["avg_sharpe"],
                    "consensus_count": signal["count"],
                    "consensus_score": score,
                    "paper_trade": self.paper_trade,
                    "stock_regime": (
                        stock_regime.regime.value if stock_regime else "unknown"
                    ),
                    "regime_penalty": regime_penalty,
                },
            ))

            if len(opportunities) >= max_positions:
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
