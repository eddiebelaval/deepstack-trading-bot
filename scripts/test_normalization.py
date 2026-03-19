"""Verify API v2 normalization works correctly."""
import asyncio
import sys
import yaml
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

    # Test normalized positions
    positions = await client.get_positions()
    print("=== NORMALIZED POSITIONS ===")
    for p in positions:
        if p["position"] != 0 or p["market_exposure"] > 0:
            print(f"  {p['ticker']}: pos={p['position']}, exposure={p['market_exposure']}c, traded={p['total_traded']}c")

    # Test normalized orders
    orders = await client.get_orders(status="resting")
    print(f"\nResting orders: {len(orders)}")
    for o in orders[:3]:
        print(f"  {o['ticker']}: count={o['count']}, remaining={o['remaining_count']}, price={o['price']}c, status={o['status']}")

    # Test normalized fills
    fills = await client.get_fills(limit=3)
    print(f"\nRecent fills: {len(fills)}")
    for f in fills[:3]:
        print(f"  {f['ticker']}: {f['count']} contracts, yes={f['yes_price']}c, no={f['no_price']}c, fee={f['fee_cost']}c")

    # Test normalized settlements
    settlements = await client.get_settlements(limit=2)
    print(f"\nRecent settlements: {len(settlements)}")
    for s in settlements[:2]:
        print(f"  {s['ticker']}: result={s['market_result']}, yes_count={s['yes_count']}, no_count={s['no_count']}, fee={s['fee_cost']}c")

    print("\nAll normalizations working correctly!")


asyncio.run(main())
