#!/usr/bin/env python3
"""
DAE PREFLIGHT CHECK
===================
Verifies all of Dae's sensory systems before live trading.
Run before every launch or after any config change.

Senses:
  SIGHT   - Can she see markets? (Kalshi API, series data)
  ACTION  - Can she act? (API auth, order placement, balance)
  THOUGHT - Can she think? (Governance, regime detection, AI analysis)
  FORESIGHT - Can she see the future? (Forward signal bridge series)
  MEMORY  - Can she remember? (SQLite journal, Supabase sync)
  VOICE   - Can she speak? (Telegram bridge, dashboard sync)
  BODY    - Is she alive? (Process, launchd, logs)

Exit code 0 = all green, 1 = warnings only, 2 = critical failures
"""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

BOT_DIR = Path(__file__).parent.parent
load_dotenv(BOT_DIR / ".env")

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"

results: list[dict] = []


def check(sense: str, name: str, passed: bool, detail: str = "", critical: bool = False):
    status = "PASS" if passed else ("CRIT" if critical else "WARN")
    color = GREEN if passed else (RED if critical else YELLOW)
    icon = "+" if passed else ("X" if critical else "!")
    results.append({"sense": sense, "name": name, "passed": passed, "critical": critical})
    print(f"  {color}[{icon}]{RESET} {name:<35} {DIM}{detail}{RESET}")


def header(sense: str, label: str):
    print(f"\n{BOLD}{sense:<12}{RESET} {label}")
    print(f"  {'─' * 50}")


# ---------------------------------------------------------------------------
# SIGHT — Can she see markets?
# ---------------------------------------------------------------------------

async def check_sight():
    header("SIGHT", "Market Data Feed")

    api_url = os.getenv("KALSHI_API_URL", "")
    check("SIGHT", "KALSHI_API_URL configured", bool(api_url), api_url[:50] if api_url else "MISSING")

    if not api_url:
        return

    async with httpx.AsyncClient(timeout=10) as client:
        # Test API connectivity
        try:
            r = await client.get(f"{api_url}/markets?status=open&limit=1",
                                 headers={"accept": "application/json"})
            check("SIGHT", "Kalshi API reachable", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as e:
            check("SIGHT", "Kalshi API reachable", False, str(e), critical=True)
            return

        # Check each configured series
        series_list = ["INXD", "KXBTC", "KXETH", "KXFED", "KXCPI", "KXGDP"]
        total_markets = 0
        for series in series_list:
            try:
                r = await client.get(
                    f"{api_url}/markets?series_ticker={series}&status=open&limit=100",
                    headers={"accept": "application/json"},
                )
                count = len(r.json().get("markets", [])) if r.status_code == 200 else 0
                total_markets += count
                check("SIGHT", f"Series {series}", count > 0, f"{count} open markets")
            except Exception as e:
                check("SIGHT", f"Series {series}", False, str(e))

        check("SIGHT", "Total tradeable markets", total_markets > 0,
              f"{total_markets} across {len(series_list)} series", critical=True)


# ---------------------------------------------------------------------------
# ACTION — Can she act?
# ---------------------------------------------------------------------------

async def check_action():
    header("ACTION", "Order Execution")

    api_url = os.getenv("KALSHI_API_URL", "")
    api_key = os.getenv("KALSHI_API_KEY_ID", "")
    check("ACTION", "API key configured", bool(api_key), f"{'***' + api_key[-4:] if api_key else 'MISSING'}")

    # Check if private key exists
    key_path = BOT_DIR / "kalshi_private_key.pem"
    alt_key = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    has_key = key_path.exists() or (alt_key and Path(alt_key).exists())
    check("ACTION", "Private key file", has_key,
          str(key_path) if key_path.exists() else (alt_key if alt_key else "NOT FOUND"),
          critical=True)

    # Test authenticated endpoint (balance)
    if api_url and api_key and has_key:
        try:
            # Test auth by signing a request the same way the bot does
            import base64
            import time
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives import hashes, serialization

            key_file = key_path if key_path.exists() else Path(alt_key)
            private_key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
            ts_ms = str(int(time.time() * 1000))
            method = "GET"
            path = "/trade-api/v2/portfolio/balance"
            msg = ts_ms + method + path
            signature = private_key.sign(
                msg.encode(),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
            sig_b64 = base64.b64encode(signature).decode()

            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{api_url}/portfolio/balance",
                    headers={
                        "KALSHI-ACCESS-KEY": api_key,
                        "KALSHI-ACCESS-SIGNATURE": sig_b64,
                        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
                    },
                )
                if r.status_code == 200:
                    balance_cents = r.json().get("balance", 0)
                    balance_usd = balance_cents / 100
                    check("ACTION", "Authenticated API access", True, f"Balance: ${balance_usd:.2f}")
                    check("ACTION", "Balance sufficient", balance_usd > 1,
                          f"${balance_usd:.2f} ({'OK' if balance_usd > 50 else 'LOW'})",
                          critical=balance_usd <= 0)
                else:
                    check("ACTION", "Authenticated API access", False,
                          f"HTTP {r.status_code}: {r.text[:100]}", critical=True)
        except Exception as e:
            check("ACTION", "Authenticated API access", False, str(e), critical=True)

    # Check paper vs live mode
    launcher = BOT_DIR / "scripts" / "bot-launcher.sh"
    if launcher.exists():
        content = launcher.read_text()
        is_paper = "--paper-balance" in content or "--paper-trade" in content
        mode = "PAPER" if is_paper else "LIVE"
        check("ACTION", "Trading mode", True, f"{mode} trading")


# ---------------------------------------------------------------------------
# THOUGHT — Can she think?
# ---------------------------------------------------------------------------

async def check_thought():
    header("THOUGHT", "Governance & Intelligence")

    # Config file
    config_path = BOT_DIR / "config.yaml"
    check("THOUGHT", "config.yaml exists", config_path.exists())

    # Check ANTHROPIC_API_KEY for AI analysis
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    check("THOUGHT", "ANTHROPIC_API_KEY (AI analysis)", bool(anthropic_key),
          "Configured" if anthropic_key else "MISSING — AI analyzer + captain's log disabled")

    # Mind files (consciousness)
    mind_dir = BOT_DIR / "kalshi_trader" / "mind"
    if mind_dir.exists():
        mind_files = list(mind_dir.rglob("*.md"))
        check("THOUGHT", "Mind files (consciousness)", len(mind_files) > 5,
              f"{len(mind_files)} files in {mind_dir.relative_to(BOT_DIR)}")

        # Check key mind subsystems
        for subdir in ["kernel", "lexicon", "models", "drives"]:
            path = mind_dir / subdir
            count = len(list(path.rglob("*.md"))) if path.exists() else 0
            check("THOUGHT", f"  mind/{subdir}/", count > 0, f"{count} files")
    else:
        check("THOUGHT", "Mind files (consciousness)", False, "mind/ directory missing", critical=True)

    # Regime history in SQLite (warm-start data)
    db_path = BOT_DIR / "trade_journal.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT regime, confidence, timestamp FROM regime_history ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if row:
                check("THOUGHT", "Regime warm-start data", True,
                      f"Last: {row[0]} (conf={row[1]:.2f}, {row[2]})")
            else:
                check("THOUGHT", "Regime warm-start data", False, "No regime history")
            conn.close()
        except Exception as e:
            check("THOUGHT", "Regime warm-start data", False, str(e))


# ---------------------------------------------------------------------------
# FORESIGHT — Can she see the future?
# ---------------------------------------------------------------------------

async def check_foresight():
    header("FORESIGHT", "Forward Signal Bridge")

    # Check forward signal series availability
    api_url = os.getenv("KALSHI_API_URL", "")
    if not api_url:
        check("FORESIGHT", "Forward signals", False, "No API URL", critical=True)
        return

    signal_series = {
        "KXFED": "RATE_SHIFT (Fed funds)",
        "KXCPI": "INFLATION (CPI)",
        "KXGDP": "GROWTH (GDP)",
        "KXBTC": "RISK_APPETITE (Bitcoin)",
        "KXETH": "RISK_APPETITE (Ethereum)",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        active = 0
        for series, label in signal_series.items():
            try:
                r = await client.get(
                    f"{api_url}/markets?series_ticker={series}&status=open&limit=5",
                    headers={"accept": "application/json"},
                )
                count = len(r.json().get("markets", [])) if r.status_code == 200 else 0
                if count > 0:
                    active += 1
                check("FORESIGHT", f"{label}", count > 0, f"{count} contracts")
            except Exception as e:
                check("FORESIGHT", f"{label}", False, str(e))

        check("FORESIGHT", "Forward signal coverage", active >= 3,
              f"{active}/5 signal sources active", critical=active == 0)


# ---------------------------------------------------------------------------
# MEMORY — Can she remember?
# ---------------------------------------------------------------------------

async def check_memory():
    header("MEMORY", "Data Persistence")

    # SQLite journal
    db_path = BOT_DIR / "trade_journal.db"
    check("MEMORY", "Trade journal (SQLite)", db_path.exists(),
          f"{db_path.stat().st_size / 1024 / 1024:.1f}MB" if db_path.exists() else "MISSING",
          critical=True)

    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            trade_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status='closed'").fetchone()[0]
            last_trade = conn.execute("SELECT created_at FROM trades ORDER BY rowid DESC LIMIT 1").fetchone()
            check("MEMORY", "Journal trades", trade_count > 0, f"{trade_count} closed trades")
            if last_trade:
                check("MEMORY", "Last journal entry", True, last_trade[0])
            conn.close()
        except Exception as e:
            check("MEMORY", "Journal readable", False, str(e), critical=True)

    # Supabase connectivity
    supa_url = os.getenv("SUPABASE_URL", "")
    supa_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    check("MEMORY", "SUPABASE_URL configured", bool(supa_url))
    check("MEMORY", "SUPABASE_SERVICE_ROLE_KEY", bool(supa_key),
          "Configured" if supa_key else "MISSING", critical=True)

    if supa_url and supa_key:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                r = await client.get(
                    f"{supa_url}/rest/v1/deepstack_trades?select=count&status=eq.closed",
                    headers={
                        "apikey": supa_key,
                        "Authorization": f"Bearer {supa_key}",
                        "Prefer": "count=exact",
                    },
                )
                if r.status_code in (200, 206):
                    # Count comes from content-range header or response body
                    count_header = r.headers.get("content-range", "")
                    if "/" in count_header:
                        count = count_header.split("/")[-1]
                    else:
                        data = r.json()
                        count = data[0].get("count", "?") if data else "?"
                    check("MEMORY", "Supabase reachable", True, f"{count} closed trades in cloud")
                else:
                    check("MEMORY", "Supabase reachable", False, f"HTTP {r.status_code}")
            except Exception as e:
                check("MEMORY", "Supabase reachable", False, str(e), critical=True)


# ---------------------------------------------------------------------------
# VOICE — Can she speak?
# ---------------------------------------------------------------------------

async def check_voice():
    header("VOICE", "Communication Channels")

    # Telegram
    tg_token = os.getenv("DAE_TELEGRAM_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    check("VOICE", "Telegram bot token", bool(tg_token),
          "Configured" if tg_token else "MISSING — no trade alerts")
    check("VOICE", "Telegram chat ID", bool(tg_chat),
          "Configured" if tg_chat else "MISSING — no trade alerts")

    if tg_token:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                r = await client.get(f"https://api.telegram.org/bot{tg_token}/getMe")
                if r.status_code == 200:
                    bot_name = r.json().get("result", {}).get("username", "?")
                    check("VOICE", "Telegram bot alive", True, f"@{bot_name}")
                else:
                    check("VOICE", "Telegram bot alive", False, f"HTTP {r.status_code}")
            except Exception as e:
                check("VOICE", "Telegram bot alive", False, str(e))

    # Dashboard
    supa_url = os.getenv("SUPABASE_URL", "")
    check("VOICE", "Dashboard sync (Supabase)", bool(supa_url), "Configured" if supa_url else "MISSING")


# ---------------------------------------------------------------------------
# BODY — Is she alive?
# ---------------------------------------------------------------------------

async def check_body():
    header("BODY", "Process Health")

    # Check launchd
    try:
        result = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=5
        )
        bot_line = [l for l in result.stdout.split("\n") if "deepstack-bot" in l]
        if bot_line:
            parts = bot_line[0].split()
            pid = parts[0] if parts[0] != "-" else None
            exit_code = parts[1] if len(parts) > 1 else "?"
            check("BODY", "launchd service registered", True, f"PID={pid}, exit={exit_code}")
            if pid and pid != "-":
                check("BODY", "Bot process running", True, f"PID {pid}")
            else:
                check("BODY", "Bot process running", False, "Not running", critical=True)
        else:
            check("BODY", "launchd service registered", False, "com.id8labs.deepstack-bot not found")
    except Exception as e:
        check("BODY", "launchd check", False, str(e))

    # Check process args
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        bot_procs = [l for l in result.stdout.split("\n") if "run_bot.py" in l and "grep" not in l]
        if bot_procs:
            is_paper = "--paper-balance" in bot_procs[0] or "--paper-trade" in bot_procs[0]
            mode = "PAPER" if is_paper else "LIVE"
            check("BODY", f"Running mode", True, f"{mode} — {'real money' if mode == 'LIVE' else 'simulated'}")
        else:
            check("BODY", "Running mode", False, "No bot process found")
    except Exception:
        pass

    # Check log recency
    log_path = Path.home() / "Library" / "Logs" / "deepstack" / "bot-stderr.log"
    if log_path.exists():
        age_seconds = (datetime.now().timestamp() - log_path.stat().st_mtime)
        age_min = age_seconds / 60
        check("BODY", "Log activity", age_min < 5,
              f"Last write {age_min:.0f}m ago" if age_min < 60 else f"Last write {age_min / 60:.1f}h ago",
              critical=age_min > 30)
    else:
        check("BODY", "Log file exists", False, str(log_path))

    # Check venv
    venv_python = BOT_DIR / "venv" / "bin" / "python3"
    check("BODY", "Python venv", venv_python.exists(), str(venv_python))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print(f"\n{BOLD}{'=' * 60}")
    print(f"  DAE PREFLIGHT CHECK")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}{RESET}")

    await check_sight()
    await check_action()
    await check_thought()
    await check_foresight()
    await check_memory()
    await check_voice()
    await check_body()

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    warnings = sum(1 for r in results if not r["passed"] and not r["critical"])
    criticals = sum(1 for r in results if not r["passed"] and r["critical"])

    print(f"\n{BOLD}{'=' * 60}")
    status_color = GREEN if criticals == 0 and warnings == 0 else (YELLOW if criticals == 0 else RED)
    status_label = "ALL GREEN" if criticals == 0 and warnings == 0 else (
        f"{warnings} WARNINGS" if criticals == 0 else f"{criticals} CRITICAL")
    print(f"  {status_color}{status_label}{RESET}  |  {passed}/{total} checks passed")

    if criticals > 0:
        print(f"\n  {RED}CRITICAL failures — DO NOT LAUNCH{RESET}")
        for r in results:
            if not r["passed"] and r["critical"]:
                print(f"    {RED}X {r['sense']}: {r['name']}{RESET}")
    elif warnings > 0:
        print(f"\n  {YELLOW}Warnings present — review before launch{RESET}")
        for r in results:
            if not r["passed"]:
                print(f"    {YELLOW}! {r['sense']}: {r['name']}{RESET}")
    else:
        print(f"\n  {GREEN}All systems nominal. Clear for launch.{RESET}")

    print(f"{'=' * 60}\n")

    if criticals > 0:
        sys.exit(2)
    elif warnings > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
