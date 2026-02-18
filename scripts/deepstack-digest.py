#!/usr/bin/env python3
"""DeepStack Daily Digest — sends a Telegram summary of trading activity.

Standalone script (not part of the bot loop). Reads from Supabase and posts
to Telegram via HYDRA bot. Designed to run via launchd at 9 PM ET daily.

Env vars (from .env or ~/.hydra/config/telegram.env):
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY — Supabase access
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   — Telegram delivery
"""

import os
import sys
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx


def load_env():
    """Load env vars from .env and HYDRA telegram config."""
    # Load project .env
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    # Load HYDRA telegram credentials
    telegram_env = Path.home() / ".hydra" / "config" / "telegram.env"
    if telegram_env.exists():
        for line in telegram_env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                # Strip surrounding quotes
                value = value.strip().strip("'\"")
                os.environ.setdefault(key.strip(), value)


def supabase_get(client: httpx.Client, table: str, params: dict | None = None) -> list:
    """GET from Supabase PostgREST."""
    url = f"{os.environ['SUPABASE_URL']}/rest/v1/{table}"
    headers = {
        "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_ROLE_KEY']}",
    }
    resp = client.get(url, headers=headers, params=params or {})
    resp.raise_for_status()
    return resp.json()


def build_message() -> str:
    """Query Supabase and build the digest message."""
    today = date.today().isoformat()

    with httpx.Client(timeout=15) as client:
        # Today's summary
        summaries = supabase_get(client, "deepstack_daily_summary", {
            "date": f"eq.{today}",
            "limit": "1",
        })

        # Strategy statuses
        strategies = supabase_get(client, "deepstack_strategy_status", {
            "order": "name",
        })

        # Health status (singleton)
        health = supabase_get(client, "deepstack_health_status", {
            "id": "eq.1",
            "limit": "1",
        })

    # Header
    lines = [f"DeepStack Daily Digest — {today}", ""]

    # Trade summary
    if summaries:
        s = summaries[0]
        total = s.get("total_trades", 0)
        wins = s.get("winning_trades", 0)
        losses = s.get("losing_trades", 0)
        net_pnl = s.get("net_pnl_cents", 0) / 100
        win_rate = (wins / total * 100) if total > 0 else 0

        lines.append(f"Trades: {total} ({wins}W / {losses}L)")
        lines.append(f"Win Rate: {win_rate:.0f}%")
        lines.append(f"Net P&L: ${net_pnl:+.2f}")

        if s.get("ending_balance_cents"):
            balance = s["ending_balance_cents"] / 100
            lines.append(f"Balance: ${balance:.2f}")
    else:
        lines.append("Trades: 0 (no activity today)")

    lines.append("")

    # Health
    if health:
        h = health[0]
        status = h.get("overall_status", "unknown").upper()
        uptime_h = (h.get("uptime_seconds", 0) or 0) / 3600
        zero_opp_cycles = h.get("cycles_with_zero_opportunities", 0)
        last_trade = h.get("last_trade_time")

        lines.append(f"Bot: {status} (uptime {uptime_h:.1f}h)")
        if zero_opp_cycles > 0:
            lines.append(f"Zero-opportunity cycles: {zero_opp_cycles}")
        if last_trade:
            lines.append(f"Last trade: {last_trade[:16].replace('T', ' ')} UTC")
    else:
        lines.append("Bot: NO HEALTH DATA")

    lines.append("")

    # Strategy statuses
    lines.append("Strategies:")
    for st in strategies:
        name = st.get("name", "?")
        enabled = st.get("enabled", False)
        status_icon = "ON" if enabled else "OFF"
        detail = ""

        if st.get("auto_disabled") and st.get("disabled_reason"):
            detail = f" [AUTO-KILLED: {st['disabled_reason'][:60]}]"

        lines.append(f"  {status_icon} {name}{detail}")

    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    """Send message via Telegram Bot API."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with httpx.Client(timeout=10) as client:
        resp = client.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })

    if resp.status_code == 200:
        print(f"Digest sent to Telegram (chat_id={chat_id})")
        return True
    else:
        print(f"Telegram API error: {resp.status_code} {resp.text}", file=sys.stderr)
        return False


def main():
    load_env()

    # Validate required vars
    required = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    message = build_message()
    print(message)
    print("---")

    if send_telegram(message):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
