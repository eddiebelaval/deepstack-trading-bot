"""One-time audit of Kalshi positions, fills, and exposure."""
import asyncio
import sys
import yaml
import json
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kalshi_trader.kalshi_client import AuthenticatedKalshiClient
from kalshi_trader.config import KalshiConfig


async def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    config = KalshiConfig(**cfg.get("kalshi", cfg))
    client = AuthenticatedKalshiClient(config)
    await client.connect()

    # All positions
    response = await client._request("GET", "/portfolio/positions")
    positions = response.get("market_positions", [])

    print("=== POSITIONS WITH HOLDINGS ===")
    total_exposure = 0
    for p in positions:
        pos = float(p.get("position_fp", 0) or 0)
        exposure = float(p.get("market_exposure_dollars", 0) or 0)
        if pos != 0 or exposure > 0:
            traded = float(p.get("total_traded_dollars", 0) or 0)
            print(f"  {p['ticker']}: position={pos:.0f}, exposure=${exposure:.2f}, traded=${traded:.2f}")
            total_exposure += exposure

    print(f"Total exposure: ${total_exposure:.2f}")

    # Today's fills
    response2 = await client._request("GET", "/portfolio/fills", params={"limit": 50})
    fills = response2.get("fills", [])
    today_fills = [f for f in fills if "2026-03-12" in f.get("created_time", "")]

    print(f"\n=== TODAY'S FILLS ({len(today_fills)}) ===")
    total_cost = 0
    for f in today_fills:
        count = float(f.get("count_fp", 0) or 0)
        side = f["side"]
        price_key = f"{side}_price_dollars"
        price = float(f.get(price_key, 0) or 0)
        cost = count * price
        total_cost += cost
        fee = float(f.get("fee_cost", 0) or 0)
        print(f"  {f['ticker']}: {side} {f['action']} {count:.0f} @ ${price:.2f} = ${cost:.2f} (fee=${fee:.4f}, taker={f.get('is_taker')})")

    print(f"Total cost today: ${total_cost:.2f}")

    # Balance
    bal = await client._request("GET", "/portfolio/balance")
    print(f"\nBalance: ${bal['balance']/100:.2f}, Portfolio: ${bal['portfolio_value']/100:.2f}")
    print(f"Total account value: ${(bal['balance'] + bal['portfolio_value'])/100:.2f}")


asyncio.run(main())
