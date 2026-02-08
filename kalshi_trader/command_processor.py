"""
Command Processor — Polls for dashboard commands and executes them on the bot.

Preferred transport: Postgres (least privilege).
Legacy fallback: Supabase PostgREST (requires service role; disabled by default).
Designed to run in a fast 3-second loop alongside the 60-second trading loop.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Supabase PostgREST configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
TABLE_PREFIX = "deepstack_"

# Prefer direct Postgres access for least privilege.
DATABASE_URL_BOT = (
    os.getenv("DATABASE_URL_BOT", "")
    or os.getenv("DEEPSTACK_DATABASE_URL", "")
    or ""
)

ALLOW_LEGACY_POSTGREST = os.getenv("DEEPSTACK_ALLOW_POSTGREST", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

try:
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover
    asyncpg = None

from .command_auth import NonceCache, split_user_params, verify_signed_command


class CommandProcessor:
    """
    Polls deepstack_bot_commands for pending commands and dispatches them.

    Each command transitions through: pending -> acknowledged -> executed/failed.
    The processor also sends periodic heartbeats to deepstack_bot_config
    so the dashboard can display bot online/offline status.
    """

    def __init__(self, bot: Any):
        self.bot = bot
        self._client: Optional[httpx.AsyncClient] = None
        self._pg_pool = None
        self._transport: str = "disabled"
        self._handlers: Dict[str, Callable] = {}
        self._nonce_cache = NonceCache()
        self._setup_handlers()

    def _get_headers(self) -> dict:
        return {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _rest_url(self, table: str) -> str:
        return f"{SUPABASE_URL}/rest/v1/{TABLE_PREFIX}{table}"

    async def connect(self) -> None:
        """Initialize HTTP client for Supabase communication."""
        # Prefer Postgres for least-privilege access.
        if DATABASE_URL_BOT:
            if asyncpg is None:
                logger.warning(
                    "DATABASE_URL_BOT set but asyncpg is not installed — "
                    "command processor disabled"
                )
                return
            try:
                self._pg_pool = await asyncpg.create_pool(DATABASE_URL_BOT, min_size=1, max_size=5, timeout=5.0)
                # Lightweight test query
                async with self._pg_pool.acquire() as conn:
                    await conn.execute("select 1")
                self._transport = "postgres"
                logger.info("Command processor connected via Postgres")
                return
            except Exception as e:
                logger.warning(f"Command processor Postgres connection failed: {e}")
                self._pg_pool = None
                self._transport = "disabled"
                return

        # Fallback to Supabase PostgREST (legacy; requires service role).
        if not ALLOW_LEGACY_POSTGREST:
            logger.warning(
                "DATABASE_URL_BOT not set and DEEPSTACK_ALLOW_POSTGREST is not enabled — "
                "command processor disabled (set DATABASE_URL_BOT or DEEPSTACK_ALLOW_POSTGREST=1)"
            )
            self._transport = "disabled"
            return

        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            logger.warning(
                "DATABASE_URL_BOT not set and SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY missing — "
                "command processor disabled"
            )
            self._transport = "disabled"
            return

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
            headers=self._get_headers(),
        )

        try:
            resp = await self._client.get(
                self._rest_url("bot_config"),
                params={"id": "eq.1", "select": "id"},
            )
            if resp.status_code == 200:
                self._transport = "postgrest"
                logger.info("Command processor connected to Supabase (PostgREST)")
            else:
                logger.warning(f"Command processor Supabase test returned {resp.status_code}")
                self._transport = "disabled"
        except Exception as e:
            logger.warning(f"Command processor connection test failed: {e}")
            self._transport = "disabled"

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None
        self._transport = "disabled"

    def _setup_handlers(self) -> None:
        """Register command handlers."""
        self._handlers = {
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "shutdown": self._handle_shutdown,
            "toggle_strategy": self._handle_toggle_strategy,
            "update_risk": self._handle_update_risk,
            "force_close": self._handle_force_close,
            "switch_profile": self._handle_switch_profile,
            "set_mode": self._handle_set_mode,
            "scan_now": self._handle_scan_now,
            "place_trade": self._handle_place_trade,
            "set_poll_interval": self._handle_set_poll_interval,
        }

    async def poll_and_execute(self) -> None:
        """Poll for pending commands and execute them."""
        if self._transport == "disabled":
            return

        try:
            if self._transport == "postgres":
                async with self._pg_pool.acquire() as conn:
                    commands = await conn.fetch(
                        """
                        select id::text as id, command, params, status, created_at
                        from deepstack_bot_commands
                        where status = 'pending'
                        order by created_at asc
                        limit 10
                        """
                    )
                # asyncpg returns Record; normalize to dict
                commands = [dict(r) for r in commands]
            else:
                # PostgREST legacy
                resp = await self._client.get(
                    self._rest_url("bot_commands"),
                    params={
                        "status": "eq.pending",
                        "order": "created_at.asc",
                        "limit": "10",
                    },
                )

                if resp.status_code != 200:
                    logger.debug(f"Command poll returned {resp.status_code}")
                    return

                commands = resp.json()
            for cmd in commands:
                await self._execute_command(cmd)

        except httpx.ConnectError:
            logger.debug("Command poll: Supabase unreachable")
        except Exception as e:
            logger.debug(f"Command poll error: {e}")

    async def _execute_command(self, cmd: dict) -> None:
        """Execute a single command and update its status."""
        command_type = cmd.get("command", "")
        command_id = cmd.get("id", "")
        params = cmd.get("params", {}) or {}

        # Backward-compat aliases:
        # - start: resume (only affects paused state; cannot resurrect a stopped process)
        # - stop: shutdown (process exits; supervisor should restart)
        aliased = command_type
        if command_type == "start":
            aliased = "resume"
        elif command_type == "stop":
            aliased = "shutdown"

        handler = self._handlers.get(aliased)
        if not handler:
            await self._update_command_status(
                command_id, "failed", {"error": f"Unknown command: {command_type}"}
            )
            return

        # Verify signature + expiry + replay. Strip meta before handler.
        vr = verify_signed_command(
            command=command_type,
            params=params,
            fallback_command_id=command_id,
            nonce_cache=self._nonce_cache,
        )
        if not vr.ok:
            await self._update_command_status(
                command_id,
                "failed",
                {"error": f"unauthorized command: {vr.error}"},
            )
            return

        user_params, _meta = split_user_params(params)

        logger.info(f"Executing command: {command_type} (id={command_id[:8]})")

        try:
            result = await handler(user_params)
            await self._update_command_status(
                command_id,
                "executed",
                result or {"status": "ok"},
            )
            logger.info(f"Command executed: {command_type}")
        except Exception as e:
            logger.error(f"Command {command_type} failed: {e}")
            await self._update_command_status(
                command_id, "failed", {"error": str(e)}
            )

    async def _update_command_status(
        self, command_id: str, status: str, result: dict
    ) -> None:
        """Update command status in Supabase."""
        try:
            if self._transport == "postgres":
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        """
                        update deepstack_bot_commands
                        set status=$1, result=$2::jsonb, executed_at=now()
                        where id=$3::uuid
                        """,
                        status,
                        json.dumps(result),
                        command_id,
                    )
            elif self._client:
                await self._client.patch(
                    self._rest_url("bot_commands"),
                    params={"id": f"eq.{command_id}"},
                    json={
                        "status": status,
                        "result": result,
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        except Exception as e:
            logger.debug(f"Failed to update command status: {e}")

    async def send_heartbeat(self) -> None:
        """Update last_heartbeat in bot_config to prove bot is alive."""
        if self._transport == "disabled":
            return

        try:
            if self._transport == "postgres":
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        """
                        update deepstack_bot_config
                        set last_heartbeat=now(), mode=$1
                        where id=1
                        """,
                        "paused" if getattr(self.bot, "_paused", False) else ("dry_run" if getattr(self.bot, "dry_run", False) else "running"),
                    )
            elif self._client:
                await self._client.patch(
                    self._rest_url("bot_config"),
                    params={"id": "eq.1"},
                    json={
                        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                        "mode": "paused" if getattr(self.bot, "_paused", False) else "running",
                    },
                )
        except Exception as e:
            logger.debug(f"Heartbeat failed: {e}")

    async def update_mode(self, mode: str) -> None:
        """Update bot mode in config table."""
        if self._transport == "disabled":
            return

        try:
            if self._transport == "postgres":
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        "update deepstack_bot_config set mode=$1 where id=1",
                        mode,
                    )
            elif self._client:
                await self._client.patch(
                    self._rest_url("bot_config"),
                    params={"id": "eq.1"},
                    json={"mode": mode},
                )
        except Exception as e:
            logger.debug(f"Mode update failed: {e}")

    # ========================================================================
    # Command Handlers
    # ========================================================================

    async def _handle_shutdown(self, params: dict) -> dict:
        """Shutdown the bot process. Supervisor should restart if desired."""
        await self.bot.stop()
        await self.update_mode("stopped")
        return {"mode": "stopped"}

    async def _handle_pause(self, params: dict) -> dict:
        """Pause trading (skip market scans, keep command polling)."""
        self.bot._paused = True
        await self.update_mode("paused")
        return {"mode": "paused"}

    async def _handle_resume(self, params: dict) -> dict:
        """Resume trading from paused state."""
        self.bot._paused = False
        await self.update_mode("running")
        return {"mode": "running"}

    async def _handle_toggle_strategy(self, params: dict) -> dict:
        """Enable or disable a strategy, persisting to Supabase immediately."""
        strategy_name = params.get("strategy", "")
        enabled = params.get("enabled", True)

        if not self.bot.strategy_manager:
            return {"error": "Not in multi-strategy mode"}

        strategies = self.bot.strategy_manager._strategies
        if strategy_name not in strategies:
            return {"error": f"Unknown strategy: {strategy_name}"}

        strategies[strategy_name].enabled = enabled

        # Persist toggle to Supabase so it survives restarts
        if self.bot.dashboard:
            await self.bot.dashboard._patch(
                "strategy_status",
                f"name=eq.{strategy_name}",
                {"enabled": enabled},
            )

        return {"strategy": strategy_name, "enabled": enabled}

    async def _handle_update_risk(self, params: dict) -> dict:
        """Update risk parameters at runtime."""
        updated = {}

        if "kelly_fraction" in params:
            kf = float(params["kelly_fraction"])
            self.bot.config.kelly_fraction = kf
            if self.bot.risk:
                self.bot.risk.kelly_sizer.kelly_fraction = kf
            updated["kelly_fraction"] = kf

        # Canonical units are cents (dashboard). Convert to dollars in bot config.
        if "max_position_size_cents" in params:
            mps = float(params["max_position_size_cents"]) / 100.0
            self.bot.config.max_position_size = mps
            updated["max_position_size"] = mps
        elif "max_position_size" in params:
            # Legacy dollars
            mps = float(params["max_position_size"])
            self.bot.config.max_position_size = mps
            updated["max_position_size"] = mps

        if "daily_loss_limit_cents" in params:
            dll = float(params["daily_loss_limit_cents"]) / 100.0
            self.bot.config.daily_loss_limit = dll
            updated["daily_loss_limit"] = dll
        elif "daily_loss_limit" in params:
            dll = float(params["daily_loss_limit"])
            self.bot.config.daily_loss_limit = dll
            updated["daily_loss_limit"] = dll

        return {"updated": updated}

    async def _handle_force_close(self, params: dict) -> dict:
        """Cancel all resting orders and close all positions at market."""
        cancelled = 0
        if self.bot.client:
            cancelled = await self.bot.client.cancel_all_orders()

        emergency = bool(params.get("emergency", False))

        closed = []
        failed = []
        would_close = []

        for ticker in list(self.bot.open_positions.keys()):
            pos = self.bot.open_positions[ticker]

            if getattr(self.bot, "dry_run", False):
                would_close.append(ticker)
                continue

            try:
                price_cents = 1
                if not emergency and self.bot.client:
                    market = await self.bot.client.get_market(ticker)
                    if market:
                        if pos["side"] == "yes":
                            price_cents = int(market.get("yes_bid", 1) or 1)
                        else:
                            price_cents = int(market.get("no_bid", 1) or 1)
                        price_cents = max(1, min(99, price_cents))

                order = await self.bot.client.create_limit_order(
                    ticker=ticker,
                    side=pos["side"],
                    action="sell",
                    count=pos["contracts"],
                    price_cents=price_cents,
                )
                if order:
                    closed.append(ticker)
                    # Only delete tracking if we successfully placed the close order.
                    del self.bot.open_positions[ticker]
            except Exception as e:
                failed.append({"ticker": ticker, "error": str(e)})

        result: dict = {"cancelled_orders": cancelled}
        if would_close:
            result["dry_run"] = True
            result["would_close"] = would_close
        result["closed_positions"] = closed
        if failed:
            result["failed"] = failed
        return result

    async def _handle_switch_profile(self, params: dict) -> dict:
        """Reload config from a named profile."""
        from .config import load_profile

        profile_name = params.get("profile", "default")
        profile_config = load_profile(profile_name)

        if not profile_config:
            return {"error": f"Profile not found: {profile_name}"}

        # Apply profile settings
        if "max_position_size" in profile_config:
            self.bot.config.max_position_size = profile_config["max_position_size"]
        if "daily_loss_limit" in profile_config:
            self.bot.config.daily_loss_limit = profile_config["daily_loss_limit"]
        if "kelly_fraction" in profile_config:
            self.bot.config.kelly_fraction = profile_config["kelly_fraction"]

        return {"profile": profile_name, "applied": profile_config}

    async def _handle_set_mode(self, params: dict) -> dict:
        """Switch between dry-run and live mode."""
        dry_run = params.get("dry_run", True)
        self.bot.dry_run = dry_run
        mode = "dry_run" if dry_run else "running"
        await self.update_mode(mode)
        return {"dry_run": dry_run, "mode": mode}

    async def _handle_scan_now(self, params: dict) -> dict:
        """Trigger an immediate trading cycle."""
        try:
            await self.bot._trading_cycle()
            return {"status": "scan_completed"}
        except Exception as e:
            return {"status": "scan_failed", "error": str(e)}

    async def _handle_place_trade(self, params: dict) -> dict:
        """Manual trade routed through bot's risk management."""
        ticker = params.get("ticker", "")
        side = params.get("side", "yes")
        contracts = int(params.get("contracts", 1))

        if not ticker:
            return {"error": "ticker is required"}

        # Run through risk checks
        risk_check = self.bot.risk.check_trade_allowed(
            ticker=ticker,
            position_size=self.bot.config.max_position_size,
        )
        if not risk_check["allowed"]:
            return {"error": "Risk check failed", "reasons": risk_check["reasons"]}

        # Get market data to determine price
        market = await self.bot.client.get_market(ticker)
        if not market or market.get("status") not in ("open", "active"):
            return {"error": f"Market {ticker} not open"}

        price = market.get("yes_ask", 50) if side == "yes" else market.get("no_ask", 50)

        if self.bot.dry_run:
            return {"status": "dry_run", "would_execute": {
                "ticker": ticker, "side": side, "contracts": contracts, "price": price
            }}

        order = await self.bot.client.create_limit_order(
            ticker=ticker, side=side, action="buy",
            count=contracts, price_cents=price,
        )

        self.bot.open_positions[ticker] = {
            "side": side,
            "contracts": contracts,
            "entry_price": price,
            "strategy": "manual",
            "entry_time": datetime.now(timezone.utc),
        }

        return {"status": "executed", "order": order, "price": price}

    async def _handle_set_poll_interval(self, params: dict) -> dict:
        """Change the trading scan frequency at runtime."""
        interval = int(params.get("interval_seconds", params.get("interval", 60)))
        interval = max(15, min(300, interval))  # Clamp to 15s-300s
        self.bot.config.poll_interval_seconds = interval
        return {"poll_interval_seconds": interval}
