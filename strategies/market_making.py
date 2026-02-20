"""
Market Making Strategy

First non-directional strategy in DeepStack. Captures bid-ask spreads
by quoting both sides of a market simultaneously.

Returns TWO TradingOpportunity objects per market (YES bid + NO bid)
linked by a shared pair_id. The existing StrategyManager handles them
as separate trades, which is correct.

Inventory management shifts quotes away from overweight side to
avoid accumulating one-sided exposure.

Expected Value:
    win_rate=0.70, avg_win=3c, avg_loss=5c
    EV = (0.70 * 3) - (0.30 * 5) = 2.10 - 1.50 = +0.60c/contract
    + potential Kalshi Liquidity Incentive Program rebates
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from .base import Strategy, TradingOpportunity, ExitSignal
from .utils import get_mid_price, is_market_tradeable

logger = logging.getLogger(__name__)

# Crypto series tickers for CryExc integration
CRYPTO_SERIES = {"KXBTC": "BTC", "KXETH": "ETH", "KXSOL": "SOL"}


class MarketMakingStrategy(Strategy):
    """
    Non-directional spread capture via two-sided quoting.

    Logic:
    1. Find markets with spreads in 3-15c range (profitable but not illiquid)
    2. Calculate fair value (mid-price) and inventory skew
    3. Return TWO opportunities per market: YES bid and NO bid
    4. Track inventory to avoid accumulating one-sided exposure
    5. Shift quotes away from overweight side (inventory management)

    Configuration:
        - min_spread_cents: Minimum spread to quote (default 3)
        - max_spread_cents: Maximum spread to quote (default 15)
        - inventory_limit: Max contracts per side before one-sided (default 10)
        - skew_per_contract: Cents to shift per contract of imbalance (default 1)
        - take_profit_cents: Target profit per leg (default 3)
        - stop_loss_cents: Max loss per leg (default 5)
        - min_volume: Minimum market volume (default 50)
    """

    MINIMUM_BALANCE_CENTS = 50_000  # $500 — strategy needs capital for two-sided quoting

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.min_spread = config.get("min_spread_cents", 3)
        self.max_spread = config.get("max_spread_cents", 15)
        self.inventory_limit = config.get("inventory_limit", 10)
        self.skew_per_contract = config.get("skew_per_contract", 1)
        self.minimum_balance_cents = config.get(
            "minimum_balance_cents", self.MINIMUM_BALANCE_CENTS
        )

        # Track inventory per ticker: {"ticker": {"yes": N, "no": M}}
        self._inventory: Dict[str, Dict[str, int]] = {}

        # CryExc bridge (injected by strategy_manager if available)
        self._cryexc_bridge = None

        logger.info(
            f"MarketMakingStrategy initialized: "
            f"spread={self.min_spread}-{self.max_spread}c, "
            f"inv_limit={self.inventory_limit}, "
            f"skew={self.skew_per_contract}c/contract"
        )

    @property
    def name(self) -> str:
        return "settlement_betting"

    @property
    def description(self) -> str:
        return "Non-directional market making with inventory management"

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
        account_balance_cents: Optional[int] = None,
    ) -> List[TradingOpportunity]:
        # Guard: market making requires sufficient capital for two-sided quoting
        if account_balance_cents is not None and account_balance_cents < self.minimum_balance_cents:
            logger.debug(
                f"[{self.name}] Skipping scan: account balance "
                f"{account_balance_cents}c (${account_balance_cents / 100:.2f}) "
                f"is below minimum {self.minimum_balance_cents}c "
                f"(${self.minimum_balance_cents / 100:.2f}) required for market making"
            )
            return []

        existing_positions = existing_positions or {}
        opportunities = []

        # Update inventory from existing positions
        self._update_inventory(existing_positions)

        for market in markets:
            ticker = market.get("ticker", "")

            if not is_market_tradeable(market, min_volume=self.min_volume):
                continue

            opps = self._analyze_market_for_quotes(market)
            opportunities.extend(opps)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        logger.info(
            f"[{self.name}] Generated {len(opportunities)} quote opportunities "
            f"from {len(markets)} markets"
        )
        return opportunities

    def _detect_crypto_symbol(self, ticker: str) -> Optional[str]:
        """Detect Kalshi crypto symbol from ticker (e.g. KXBTC-... -> BTC)."""
        upper = ticker.upper()
        for prefix, symbol in CRYPTO_SERIES.items():
            if upper.startswith(prefix):
                return symbol
        return None

    def _analyze_market_for_quotes(
        self, market: Dict[str, Any]
    ) -> List[TradingOpportunity]:
        """
        Analyze a market and generate 0 or 2 quote opportunities.
        Returns a YES bid and NO bid if the spread is in range.

        When CryExc is active:
        - Tight exchange spread = 10pt bonus (more predictable fair value)
        - Liquidation cascade = skip quoting (capital preservation)
        """
        ticker = market.get("ticker", "")
        title = market.get("title", "")
        yes_bid = market.get("yes_bid", 0)
        yes_ask = market.get("yes_ask", 0)
        no_bid = market.get("no_bid", 0)
        no_ask = market.get("no_ask", 0)
        volume = market.get("volume", 0) or market.get("volume_24h", 0)

        # Liquidation cascade protection: skip quoting during cascades
        crypto_symbol = self._detect_crypto_symbol(ticker)
        if crypto_symbol and self._cryexc_bridge:
            store = self._cryexc_bridge.get_signal_store(crypto_symbol)
            if store and not store.is_stale():
                liq_signal = store.get_liquidation_signal()
                if liq_signal.get("is_cascade", False):
                    logger.info(
                        f"[{self.name}] Skipping {ticker}: liquidation cascade "
                        f"({liq_signal.get('count', 0)} events, "
                        f"${liq_signal.get('total_notional', 0):,.0f} notional)"
                    )
                    return []

        # Check spreads
        yes_spread = (yes_ask - yes_bid) if (yes_ask and yes_bid) else 0
        no_spread = (no_ask - no_bid) if (no_ask and no_bid) else 0

        if yes_spread < self.min_spread or no_spread < self.min_spread:
            return []
        if yes_spread > self.max_spread or no_spread > self.max_spread:
            return []

        mid = get_mid_price(market)

        # Calculate inventory skew
        inv = self._inventory.get(ticker, {"yes": 0, "no": 0})
        yes_inv = inv.get("yes", 0)
        no_inv = inv.get("no", 0)
        net_exposure = yes_inv - no_inv  # Positive = long YES

        # Skew adjustment: shift prices to reduce inventory
        skew = net_exposure * self.skew_per_contract

        # Our YES bid: slightly above current yes_bid, adjusted for skew
        our_yes_bid = yes_bid + 1 - skew
        # Our NO bid: slightly above current no_bid, adjusted for skew
        our_no_bid = no_bid + 1 + skew

        # Clamp to valid range
        our_yes_bid = max(1, min(99, int(our_yes_bid)))
        our_no_bid = max(1, min(99, int(our_no_bid)))

        # Score based on spread capture potential
        avg_spread = (yes_spread + no_spread) / 2
        spread_score = min(50, avg_spread * 5)
        volume_score = min(30, volume / 100 * 30)
        inv_score = 20 * (1 - abs(net_exposure) / max(self.inventory_limit, 1))

        # Exchange depth bonus: tight exchange spread = more predictable fair value
        depth_bonus = 0.0
        if crypto_symbol and self._cryexc_bridge:
            store = self._cryexc_bridge.get_signal_store(crypto_symbol)
            if store and not store.is_stale():
                ob = store.get_orderbook_imbalance()
                if ob:
                    exchange_spread = ob.get("spread", 0)
                    mid_price = ob.get("mid_price", 1)
                    if mid_price > 0:
                        # Spread as bps of mid price
                        spread_bps = (exchange_spread / mid_price) * 10000
                        # Tight spread (<5 bps) = 10pt bonus, scaling down to 0 at 20 bps
                        if spread_bps < 20:
                            depth_bonus = max(0, 10 * (1 - spread_bps / 20))

        total_score = max(0, min(100, spread_score + volume_score + inv_score + depth_bonus))

        if total_score < self.min_score:
            return []

        pair_id = str(uuid.uuid4())[:8]
        results = []

        # YES bid — only if not at inventory limit on YES side
        if yes_inv < self.inventory_limit:
            results.append(TradingOpportunity(
                ticker=ticker,
                title=title,
                side="yes",
                entry_price_cents=our_yes_bid,
                current_yes_price=mid,
                current_no_price=100 - mid,
                volume=volume,
                score=total_score,
                reasoning=(
                    f"MM YES bid: {our_yes_bid}c (spread: {yes_spread}c, "
                    f"inv: {yes_inv}Y/{no_inv}N, skew: {skew:+d}c)"
                ),
                expected_profit_cents=self.take_profit,
                max_loss_cents=self.stop_loss,
                strategy_name=self.name,
                metadata={
                    "pair_id": pair_id,
                    "quote_side": "yes_bid",
                    "spread": yes_spread,
                    "inventory_yes": yes_inv,
                    "inventory_no": no_inv,
                    "skew": skew,
                },
            ))

        # NO bid — only if not at inventory limit on NO side
        if no_inv < self.inventory_limit:
            results.append(TradingOpportunity(
                ticker=ticker,
                title=title,
                side="no",
                entry_price_cents=our_no_bid,
                current_yes_price=mid,
                current_no_price=100 - mid,
                volume=volume,
                score=total_score,
                reasoning=(
                    f"MM NO bid: {our_no_bid}c (spread: {no_spread}c, "
                    f"inv: {yes_inv}Y/{no_inv}N, skew: {skew:+d}c)"
                ),
                expected_profit_cents=self.take_profit,
                max_loss_cents=self.stop_loss,
                strategy_name=self.name,
                metadata={
                    "pair_id": pair_id,
                    "quote_side": "no_bid",
                    "spread": no_spread,
                    "inventory_yes": yes_inv,
                    "inventory_no": no_inv,
                    "skew": skew,
                },
            ))

        return results

    def _update_inventory(self, existing_positions: Dict[str, Any]):
        """Update internal inventory tracking from existing positions."""
        self._inventory.clear()
        for ticker, pos in existing_positions.items():
            if pos.get("strategy_name") != self.name:
                continue
            side = pos.get("side", "yes")
            contracts = pos.get("contracts", 1)
            if ticker not in self._inventory:
                self._inventory[ticker] = {"yes": 0, "no": 0}
            self._inventory[ticker][side] += contracts

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        entry_price = position.get("entry_price", 50)
        pnl_cents = current_price - entry_price

        # Take profit (tight for market making)
        if pnl_cents >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"MM take profit: +{pnl_cents}c",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=0.9,
            )

        # Stop loss
        if pnl_cents <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"MM stop loss: {pnl_cents}c",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl_cents,
                urgency=1.0,
            )

        return ExitSignal(
            should_exit=False,
            reason=f"MM holding: {pnl_cents:+d}c (TP: +{self.take_profit}c, SL: -{self.stop_loss}c)",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl_cents,
            urgency=0.0,
        )

    def _get_prior_stats(self) -> Dict[str, float]:
        # Neutral priors — let Bayesian learning converge to reality
        return {
            "win_rate": 0.50,
            "avg_win_cents": 6.0,
            "avg_loss_cents": 6.0,
        }
