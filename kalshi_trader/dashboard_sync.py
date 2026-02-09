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
            "Prefer": "return=minimal",
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
            )
            return response.status_code in (200, 204)
        except Exception as e:
            logger.debug(f"Dashboard sync patch error on {table}: {e}")
            return False

    async def _upsert(self, table: str, data: Dict[str, Any], on_conflict: str = "") -> bool:
        """Fire-and-forget upsert to Supabase PostgREST."""
        if not self._client or not self._supabase_url:
            return False

        try:
            headers = {**self._get_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
            response = await self._client.post(
                self._rest_url(table),
                json=data,
                headers=headers,
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
            "kelly_fraction": risk_config.get("kelly_fraction", 0.5),
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
            await self._upsert("strategy_status", {
                "name": strategy["name"],
                "enabled": strategy.get("enabled", True),
                "active_positions": strategy.get("active_positions", 0),
                "opportunities_found": strategy.get("opportunities_found", 0),
                "last_scan": strategy.get("last_scan"),
                "status": strategy.get("status", "inactive"),
            })

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
