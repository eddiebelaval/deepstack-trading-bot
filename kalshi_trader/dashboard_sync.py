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

# Prefer direct Postgres access for least privilege.
DATABASE_URL_BOT = (
    os.getenv("DATABASE_URL_BOT", "")
    or os.getenv("DEEPSTACK_DATABASE_URL", "")
    or ""
)

try:
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover
    asyncpg = None


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
        self._pg_pool = None
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
        # Prefer Postgres for least-privilege runtime access.
        if DATABASE_URL_BOT:
            if asyncpg is None:
                logger.warning(
                    "DATABASE_URL_BOT set but asyncpg is not installed — dashboard sync disabled"
                )
                self._available = False
                return
            try:
                self._pg_pool = await asyncpg.create_pool(DATABASE_URL_BOT, min_size=1, max_size=5, timeout=5.0)
                async with self._pg_pool.acquire() as conn:
                    await conn.execute("select 1")
                logger.info("Dashboard sync connected via Postgres")
                self._available = True
                return
            except Exception as e:
                logger.warning(f"Dashboard sync Postgres connection failed: {e}")
                self._available = False
                self._pg_pool = None
                return

        # Fallback to Supabase PostgREST (legacy; requires service role).
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
            headers=self._get_headers(),
        )

        if not self._supabase_url or not SUPABASE_SERVICE_KEY:
            logger.warning(
                "DATABASE_URL_BOT not set and SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY missing — "
                "dashboard sync disabled"
            )
            self._available = False
            return

        try:
            response = await self._client.get(
                self._rest_url("bot_config"),
                params={"id": "eq.1", "select": "id"},
            )
            if response.status_code == 200:
                logger.info("Dashboard sync connected to Supabase (PostgREST)")
                self._available = True
            else:
                logger.warning(f"Supabase returned {response.status_code} — sync will retry")
                self._available = False
        except Exception:
            logger.warning("Supabase not reachable — sync disabled until available")
            self._available = False

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None

    async def get_strategy_overrides(self) -> Dict[str, bool]:
        """Read strategy enabled states from Supabase to restore user toggles across restarts."""
        if not self._available:
            return {}

        try:
            if self._pg_pool:
                async with self._pg_pool.acquire() as conn:
                    rows = await conn.fetch("select name, enabled from deepstack_strategy_status")
                overrides = {r["name"]: bool(r["enabled"]) for r in rows}
                return overrides

            if not self._client:
                return {}
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
        if not self._available:
            return False

        try:
            if self._pg_pool:
                # Only support simple eq filters used by the bot (name=eq.X or id=eq.1).
                where_sql = ""
                where_args: List[Any] = []
                if filters.startswith("name=eq."):
                    where_sql = "where name = $1"
                    where_args = [filters.split("name=eq.", 1)[1]]
                elif filters.startswith("id=eq."):
                    where_sql = "where id = $1"
                    where_args = [int(filters.split("id=eq.", 1)[1])]
                else:
                    return False

                keys = list(data.keys())
                if not keys:
                    return True

                set_parts = []
                args: List[Any] = []
                for i, k in enumerate(keys, start=1):
                    set_parts.append(f"{k} = ${i}")
                    args.append(data[k])
                args.extend(where_args)

                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        f"update {TABLE_PREFIX}{table} set {', '.join(set_parts)} {where_sql}",
                        *args,
                    )
                return True

            if not self._client or not self._supabase_url:
                return False
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
        if not self._available:
            return False

        try:
            if self._pg_pool:
                # Only used for strategy_status upserts today (unique name).
                if table != "strategy_status":
                    return False
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        """
                        insert into deepstack_strategy_status
                          (name, enabled, active_positions, opportunities_found, last_scan, status)
                        values
                          ($1, $2, $3, $4, $5::timestamptz, $6)
                        on conflict (name) do update set
                          enabled = excluded.enabled,
                          active_positions = excluded.active_positions,
                          opportunities_found = excluded.opportunities_found,
                          last_scan = excluded.last_scan,
                          status = excluded.status
                        """,
                        data.get("name"),
                        data.get("enabled", True),
                        data.get("active_positions", 0),
                        data.get("opportunities_found", 0),
                        data.get("last_scan"),
                        data.get("status", "inactive"),
                    )
                return True

            if not self._client or not self._supabase_url:
                return False
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
        if self._pg_pool:
            try:
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        """
                        insert into deepstack_dashboard_state (
                          timestamp, balance_cents, daily_pnl_cents, daily_pnl_percentage,
                          total_positions, available_balance_cents,
                          daily_loss_limit_cents, daily_loss_used_cents,
                          max_position_size_cents, kelly_fraction,
                          positions_at_risk, risk_percentage
                        ) values (now(), $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                        """,
                        state["balance_cents"],
                        state["daily_pnl_cents"],
                        state["daily_pnl_percentage"],
                        state["total_positions"],
                        state["available_balance_cents"],
                        state["daily_loss_limit_cents"],
                        state["daily_loss_used_cents"],
                        state["max_position_size_cents"],
                        state["kelly_fraction"],
                        state["positions_at_risk"],
                        state["risk_percentage"],
                    )
            except Exception as e:
                logger.debug(f"Dashboard sync error on dashboard_state: {e}")
        else:
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
        if self._pg_pool:
            try:
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        """
                        insert into deepstack_trades (
                          market_ticker, side, action, contracts, entry_price_cents,
                          status, strategy, order_id, reasoning, session_date
                        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::date)
                        """,
                        trade["market_ticker"],
                        trade["side"],
                        trade["action"],
                        trade["contracts"],
                        trade["entry_price_cents"],
                        trade["status"],
                        trade["strategy"],
                        trade["order_id"],
                        trade["reasoning"],
                        trade["session_date"],
                    )
            except Exception as e:
                logger.debug(f"Dashboard sync error on trades: {e}")
        else:
            await self._post("trades", trade)

    async def push_trade_close(
        self,
        trade_id: str,
        exit_price_cents: int,
        pnl_cents: int,
        exit_reason: str,
    ) -> None:
        """Push a trade close/update to Supabase."""
        if not self._client or not self._supabase_url:
            return

        try:
            await self._client.patch(
                self._rest_url("trades"),
                params={"id": f"eq.{trade_id}"},
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
        if self._pg_pool:
            try:
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        "insert into deepstack_log_entries (level, strategy, message) values ($1,$2,$3)",
                        entry["level"],
                        entry["strategy"],
                        entry["message"],
                    )
            except Exception as e:
                logger.debug(f"Dashboard sync error on log_entries: {e}")
        else:
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
        if self._pg_pool:
            try:
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        """
                        insert into deepstack_opportunities (
                          market_ticker, strategy, side,
                          current_price_cents, target_price_cents,
                          expected_profit_pct, confidence, status, reasoning
                        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        """,
                        opp["market_ticker"],
                        opp["strategy"],
                        opp["side"],
                        opp["current_price_cents"],
                        opp["target_price_cents"],
                        opp["expected_profit_pct"],
                        opp["confidence"],
                        opp["status"],
                        opp["reasoning"],
                    )
            except Exception as e:
                logger.debug(f"Dashboard sync error on opportunities: {e}")
        else:
            await self._post("opportunities", opp)
