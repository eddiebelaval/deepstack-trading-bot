"""
Dashboard Sync — Fire-and-forget bridge from bot to Supabase.

Pushes real-time trading data directly to Supabase PostgREST API,
replacing the previous localhost dashboard dependency. The dashboard
reads from the same Supabase tables, making data available whether
or not the dashboard is running.

Tables written to (all prefixed deepstack_):
  deepstack_dashboard_state  — account balance, risk metrics, strategy state
  deepstack_trades           — trade executions
  deepstack_log_entries      — log entries for the live feed
  deepstack_opportunities    — detected opportunities
  deepstack_strategy_status  — per-strategy status updates
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
TABLE_PREFIX = "deepstack_"


class DashboardSync:
    """
    Pushes bot state to Supabase PostgREST API.

    All methods are fire-and-forget — errors are logged but never
    propagate to the caller. Trading continues regardless of
    Supabase availability.
    """

    def __init__(self, base_url: Optional[str] = None):
        # base_url param kept for backward compatibility but ignored
        self._supabase_url = SUPABASE_URL
        self._client: Optional[httpx.AsyncClient] = None
        self._available = True

    def _get_headers(self) -> dict:
        return {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        }

    def _rest_url(self, table: str) -> str:
        return f"{self._supabase_url}/rest/v1/{TABLE_PREFIX}{table}"

    async def connect(self) -> None:
        """Initialize HTTP client for Supabase communication."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
            headers=self._get_headers(),
        )

        if not self._supabase_url or not SUPABASE_SERVICE_KEY:
            logger.warning(
                "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set — "
                "dashboard sync disabled"
            )
            self._available = False
            return

        # Test connection
        try:
            response = await self._client.get(
                self._rest_url("bot_config"),
                params={"id": "eq.1", "select": "id"},
            )
            if response.status_code == 200:
                logger.info(f"Dashboard sync connected to Supabase")
                self._available = True
            else:
                logger.warning(
                    f"Supabase returned {response.status_code} — sync will retry"
                )
                self._available = False
        except Exception:
            logger.warning("Supabase not reachable — sync disabled until available")
            self._available = False

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_strategy_overrides(self) -> Dict[str, bool]:
        """Read strategy enabled states from Supabase to restore user toggles across restarts."""
        if not self._client or not self._available:
            return {}

        try:
            response = await self._client.get(
                self._rest_url("strategy_status"),
                params={"select": "name,enabled"},
            )
            if response.status_code == 200:
                rows = response.json()
                overrides = {row["name"]: row["enabled"] for row in rows}
                logger.info(f"Restored strategy overrides from Supabase: {len(overrides)} strategies")
                return overrides
            else:
                logger.debug(f"Failed to read strategy overrides: {response.status_code}")
                return {}
        except Exception as e:
            logger.debug(f"Could not restore strategy overrides: {e}")
            return {}

    async def _post(self, table: str, data: Dict[str, Any]) -> bool:
        """Fire-and-forget POST to Supabase PostgREST."""
        if not self._client or not self._supabase_url:
            return False

        try:
            response = await self._client.post(
                self._rest_url(table),
                json=data,
                headers={"Prefer": "return=minimal"},
            )
            if response.status_code in (200, 201):
                if not self._available:
                    logger.info("Dashboard sync reconnected to Supabase")
                    self._available = True
                return True
            else:
                logger.debug(
                    f"Supabase POST {table} returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
                return False
        except httpx.ConnectError:
            if self._available:
                logger.warning("Supabase connection lost — will retry silently")
                self._available = False
            return False
        except Exception as e:
            logger.debug(f"Dashboard sync error on {table}: {e}")
            return False

    async def _patch(self, table: str, filters: str, data: Dict[str, Any]) -> bool:
        """Fire-and-forget PATCH to Supabase PostgREST."""
        if not self._client or not self._supabase_url:
            return False

        try:
            response = await self._client.patch(
                f"{self._rest_url(table)}?{filters}",
                json=data,
                headers={"Prefer": "return=minimal"},
            )
            return response.status_code in (200, 204)
        except Exception as e:
            logger.debug(f"Dashboard sync patch error on {table}: {e}")
            return False

    async def _upsert(self, table: str, data: Dict[str, Any], on_conflict: str = "id") -> bool:
        """Fire-and-forget upsert to Supabase PostgREST.

        PostgREST requires the `on_conflict` query parameter to identify
        which unique constraint to use for merge-duplicates resolution.
        Without it, duplicate keys return 409 even with the Prefer header.
        """
        if not self._client or not self._supabase_url:
            return False

        try:
            url = f"{self._rest_url(table)}?on_conflict={on_conflict}"
            response = await self._client.post(
                url,
                json=data,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            return response.status_code in (200, 201)
        except Exception as e:
            logger.debug(f"Dashboard sync upsert error on {table}: {e}")
            return False

    async def push_state(
        self,
        balance_cents: int,
        available_balance_cents: int,
        daily_pnl_cents: int,
        total_positions: int,
        strategies: List[Dict[str, Any]],
        risk_config: Dict[str, Any],
    ) -> None:
        """Push full dashboard state (called each trading cycle)."""
        daily_pnl_pct = 0.0
        if balance_cents > 0:
            daily_pnl_pct = round((daily_pnl_cents / balance_cents) * 100, 2)

        # Insert into dashboard_state
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance_cents": balance_cents,
            "daily_pnl_cents": daily_pnl_cents,
            "daily_pnl_percentage": daily_pnl_pct,
            "total_positions": total_positions,
            "available_balance_cents": available_balance_cents,
            "daily_loss_limit_cents": int(
                risk_config.get("daily_loss_limit", 100) * 100
            ),
            "daily_loss_used_cents": abs(daily_pnl_cents) if daily_pnl_cents < 0 else 0,
            "max_position_size_cents": int(
                risk_config.get("max_position_size", 50) * 100
            ),
            "kelly_fraction": risk_config.get("kelly_fraction", 0.02),
            "positions_at_risk": total_positions,
            "risk_percentage": round(
                (
                    total_positions
                    / max(risk_config.get("max_position_size", 50), 1)
                )
                * 100,
                1,
            ),
        }
        await self._post("dashboard_state", state)

        # Update strategy_status rows
        for strategy in strategies:
            row = {
                "name": strategy["name"],
                "enabled": strategy.get("enabled", True),
                "active_positions": strategy.get("active_positions", 0),
                "opportunities_found": strategy.get("opportunities_found", 0),
                "last_scan": strategy.get("last_scan"),
                "status": strategy.get("status", "inactive"),
            }
            # Forward learning stats when present (populated by PerformanceTracker)
            for key in ("blended_win_rate", "learning_confidence", "effective_trades",
                        "blended_ev_cents", "health_status", "auto_disabled"):
                if key in strategy:
                    row[key] = strategy[key]
            await self._upsert("strategy_status", row, on_conflict="name")

    async def push_trade(
        self,
        market_ticker: str,
        side: str,
        action: str,
        contracts: int,
        entry_price_cents: int,
        strategy: str,
        order_id: Optional[str] = None,
        reasoning: Optional[str] = None,
    ) -> None:
        """Push a trade execution to Supabase."""
        trade = {
            "market_ticker": market_ticker,
            "side": side.upper(),
            "action": action.upper(),
            "contracts": contracts,
            "entry_price_cents": entry_price_cents,
            "status": "open",
            "strategy": strategy,
            "order_id": order_id,
            "reasoning": reasoning,
            "session_date": datetime.now().strftime("%Y-%m-%d"),
        }
        await self._post("trades", trade)

    async def push_trade_close(
        self,
        order_id: str,
        exit_price_cents: int,
        pnl_cents: int,
        exit_reason: str,
    ) -> None:
        """Push a trade close/update to Supabase. Matches by order_id."""
        if not self._client or not self._supabase_url:
            return

        try:
            await self._client.patch(
                self._rest_url("trades"),
                params={"order_id": f"eq.{order_id}"},
                json={
                    "exit_price_cents": exit_price_cents,
                    "pnl_cents": pnl_cents,
                    "status": "closed",
                    "exit_reason": exit_reason,
                },
            )
        except Exception:
            pass

    async def push_log(
        self,
        message: str,
        level: str = "INFO",
        strategy: Optional[str] = None,
    ) -> None:
        """Push a log entry to Supabase."""
        entry = {
            "level": level,
            "strategy": strategy,
            "message": message,
        }
        await self._post("log_entries", entry)

    async def push_opportunity(
        self,
        market_ticker: str,
        strategy: str,
        side: str,
        current_price_cents: int,
        target_price_cents: int,
        confidence: float,
        reasoning: Optional[str] = None,
    ) -> None:
        """Push a detected opportunity to Supabase."""
        expected_profit = 0.0
        if current_price_cents > 0:
            expected_profit = round(
                ((target_price_cents - current_price_cents) / current_price_cents)
                * 100,
                2,
            )

        opp = {
            "market_ticker": market_ticker,
            "strategy": strategy,
            "side": side.upper(),
            "current_price_cents": current_price_cents,
            "target_price_cents": target_price_cents,
            "expected_profit_pct": expected_profit,
            "confidence": confidence,
            "status": "active",
            "reasoning": reasoning,
        }
        await self._post("opportunities", opp)

    async def push_positions(self, positions: List[Dict[str, Any]]) -> None:
        """Upsert position snapshots to Supabase (one row per ticker)."""
        now = datetime.now(timezone.utc).isoformat()
        for pos in positions:
            await self._upsert("positions", {
                "ticker": pos["ticker"],
                "market_title": pos.get("market_title"),
                "side": pos.get("side", "yes"),
                "contracts": pos.get("contracts", 0),
                "position": pos.get("position", 0),
                "total_traded": pos.get("total_traded", 0),
                "market_exposure": pos.get("market_exposure", 0),
                "realized_pnl": pos.get("realized_pnl", 0),
                "fees_paid": pos.get("fees_paid", 0),
                "resting_orders_count": pos.get("resting_orders_count", 0),
                "current_price": pos.get("current_price"),
                "market_value_cents": pos.get("market_value_cents"),
                "avg_entry_price_cents": pos.get("avg_entry_price_cents"),
                "volume_24h": pos.get("volume_24h", 0),
                "open_interest": pos.get("open_interest", 0),
                "previous_price": pos.get("previous_price"),
                "last_updated_ts": pos.get("last_updated_ts"),
                "synced_at": now,
            }, on_conflict="ticker")

        # Remove stale positions (closed on exchange but still in Supabase)
        active_tickers = {p["ticker"] for p in positions}
        if self._client and self._supabase_url:
            try:
                # Fetch current tickers in table
                resp = await self._client.get(
                    self._rest_url("positions"),
                    params={"select": "ticker"},
                )
                if resp.status_code == 200:
                    db_tickers = {row["ticker"] for row in resp.json()}
                    stale = db_tickers - active_tickers
                    for ticker in stale:
                        await self._client.delete(
                            self._rest_url("positions"),
                            params={"ticker": f"eq.{ticker}"},
                            headers=self._get_headers(),
                        )
            except Exception as e:
                logger.debug(f"Failed to clean stale positions: {e}")

    async def push_orders(self, orders: List[Dict[str, Any]]) -> None:
        """Upsert order snapshots to Supabase (one row per order_id)."""
        now = datetime.now(timezone.utc).isoformat()
        synced_ids = set()
        for order in orders:
            oid = order.get("order_id")
            if not oid:
                continue
            synced_ids.add(oid)
            await self._upsert("orders", {
                "order_id": oid,
                "ticker": order.get("ticker", ""),
                "side": order.get("side", "yes"),
                "action": order.get("action", "buy"),
                "type": order.get("type", "limit"),
                "status": order.get("status", "resting"),
                "yes_price": order.get("yes_price"),
                "no_price": order.get("no_price"),
                "initial_count": order.get("initial_count", 0),
                "remaining_count": order.get("remaining_count", 0),
                "fill_count": order.get("fill_count", 0),
                "taker_fees": order.get("taker_fees", 0),
                "maker_fees": order.get("maker_fees", 0),
                "taker_fill_cost": order.get("taker_fill_cost", 0),
                "maker_fill_cost": order.get("maker_fill_cost", 0),
                "created_time": order.get("created_time"),
                "last_update_time": order.get("last_update_time"),
                "expiration_time": order.get("expiration_time"),
                "synced_at": now,
            }, on_conflict="order_id")

    async def push_fills(self, fills: List[Dict[str, Any]]) -> None:
        """Append new fills to Supabase (skip duplicates via unique fill_id)."""
        for fill in fills:
            fid = fill.get("fill_id")
            if not fid:
                continue
            await self._upsert("fills", {
                "fill_id": fid,
                "order_id": fill.get("order_id"),
                "ticker": fill.get("ticker", ""),
                "side": fill.get("side", "yes"),
                "action": fill.get("action", "buy"),
                "count": fill.get("count", 0),
                "yes_price": fill.get("yes_price"),
                "no_price": fill.get("no_price"),
                "is_taker": fill.get("is_taker", False),
                "fee_cost": fill.get("fee_cost"),
                "created_time": fill.get("created_time"),
            }, on_conflict="fill_id")

    async def push_settlements(self, settlements: List[Dict[str, Any]]) -> None:
        """Upsert settlement records to Supabase (one row per ticker)."""
        for s in settlements:
            ticker = s.get("ticker")
            if not ticker:
                continue
            await self._upsert("settlements", {
                "ticker": ticker,
                "event_ticker": s.get("event_ticker"),
                "market_result": s.get("market_result", "void"),
                "yes_count": s.get("yes_count", 0),
                "no_count": s.get("no_count", 0),
                "yes_total_cost": s.get("yes_total_cost", 0),
                "no_total_cost": s.get("no_total_cost", 0),
                "revenue": s.get("revenue", 0),
                "settled_time": s.get("settled_time"),
                "fee_cost": s.get("fee_cost"),
                "value": s.get("value"),
            }, on_conflict="ticker")

    async def push_captains_log(
        self,
        content: str,
        role: str = "bot",
        event_type: Optional[str] = None,
        priority: str = "routine",
        strategy: Optional[str] = None,
        regime: Optional[str] = None,
        model_used: Optional[str] = None,
        tokens_used: Optional[int] = None,
    ) -> None:
        """Push a Captain's Log entry to Supabase."""
        entry: Dict[str, Any] = {
            "role": role,
            "content": content,
            "event_type": event_type,
            "priority": priority,
        }
        if strategy:
            entry["strategy"] = strategy
        if regime:
            entry["regime"] = regime
        if model_used:
            entry["model_used"] = model_used
        if tokens_used is not None:
            entry["tokens_used"] = tokens_used
        await self._post("captains_log", entry)

    async def push_regime(
        self,
        regime: str,
        confidence: float,
        volatility: float,
        trend_strength: float,
        mean_reversion_score: float,
        volume_ratio: float,
        num_markets: int,
    ) -> None:
        """Push a regime snapshot to Supabase for dashboard visualization."""
        await self._post("regime_history", {
            "regime": regime,
            "confidence": confidence,
            "volatility": volatility,
            "trend_strength": trend_strength,
            "mean_reversion_score": mean_reversion_score,
            "volume_ratio": volume_ratio,
            "num_markets_sampled": num_markets,
        })

    async def update_strategy_disabled(
        self,
        name: str,
        reason: str,
        disabled_by: str = "auto",
    ) -> None:
        """Persist disabled_reason to strategy_status so it survives bot restarts."""
        await self._patch(
            "strategy_status",
            f"name=eq.{name}",
            {
                "auto_disabled": True,
                "disabled_reason": reason,
                "disabled_at": datetime.now(timezone.utc).isoformat(),
                "disabled_by": disabled_by,
            },
        )

    async def push_governance_decision(
        self,
        regime: str,
        confidence: float,
        action: str,
        strategy_name: Optional[str],
        reason: str,
        mode: str,
    ) -> None:
        """Push a governance decision to Supabase for audit trail."""
        await self._post("governance_decisions", {
            "regime": regime,
            "regime_confidence": confidence,
            "action": action,
            "strategy_name": strategy_name,
            "reason": reason,
            "mode": mode,
        })
