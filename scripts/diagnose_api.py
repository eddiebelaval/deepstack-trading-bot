"""
Dae API Diagnostic — Test Kalshi connectivity and market data.

Run standalone to verify:
  1. API authentication (RSA-PSS signing)
  2. Account balance and positions
  3. Market data for each configured series
  4. Response structure validation

Usage:
    python scripts/diagnose_api.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env
env_file = _PROJECT_ROOT / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

from kalshi_trader.config import load_config, get_strategy_configs
from kalshi_trader.kalshi_client import AuthenticatedKalshiClient


async def main():
    print("=" * 60)
    print("DAE API DIAGNOSTIC")
    print("=" * 60)
    print()

    # Load config
    config = load_config()
    valid, error = config.validate_credentials()
    if not valid:
        print(f"FAIL: Credentials invalid — {error}")
        return

    print(f"API URL: {config.effective_base_url}")
    print(f"API Key: {config.api_key_id[:8]}...")
    print()

    # Connect
    client = AuthenticatedKalshiClient(config)
    try:
        await client.connect()
        print("AUTH: OK (connected)")
    except Exception as e:
        print(f"AUTH: FAIL — {e}")
        return

    # Balance
    try:
        balance = await client.get_balance()
        cash = balance.get("balance", 0)
        portfolio = balance.get("portfolio_value", 0)
        print(f"BALANCE: ${cash:.2f} cash, ${portfolio:.2f} portfolio value")
    except Exception as e:
        print(f"BALANCE: FAIL — {e}")

    # Positions
    try:
        positions = await client.get_positions()
        print(f"POSITIONS: {len(positions)} open")
        for p in positions[:5]:
            ticker = p.get("ticker", "?")
            contracts = p.get("contracts", 0)
            side = p.get("side", "?")
            print(f"  {ticker}: {side} x{contracts}")
        if len(positions) > 5:
            print(f"  ... and {len(positions) - 5} more")
    except Exception as e:
        print(f"POSITIONS: FAIL — {e}")

    print()
    print("--- Market Data Tests ---")
    print()

    # Test each configured series
    strategy_configs = get_strategy_configs()
    tested_series = set()

    for sc in strategy_configs:
        if not sc.get("enabled"):
            continue
        for market in sc.get("markets", []):
            series = market.get("series", "")
            if not series or series in tested_series or series == "*":
                continue
            tested_series.add(series)

            try:
                markets = await client.get_markets(
                    series_ticker=series, status="open", limit=5
                )
                if markets:
                    print(f"  {series}: {len(markets)} open markets")
                    for m in markets[:3]:
                        print(
                            f"    {m.get('ticker', '?')} — "
                            f"bid={m.get('yes_bid', 0)} ask={m.get('yes_ask', 0)} "
                            f"vol={m.get('volume', 0)}"
                        )
                else:
                    print(f"  {series}: 0 markets (series may have no open contracts)")
            except Exception as e:
                print(f"  {series}: FAIL — {e}")

    # Test raw market fetch (no series filter) to verify API works at all
    print()
    try:
        all_markets = await client.get_markets(status="open", limit=5)
        print(f"ALL MARKETS (no filter): {len(all_markets)} returned")
        for m in all_markets[:3]:
            print(
                f"  {m.get('ticker', '?')} — {m.get('title', '?')[:50]}"
            )
    except Exception as e:
        print(f"ALL MARKETS: FAIL — {e}")

    await client.disconnect()

    print()
    print("=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
