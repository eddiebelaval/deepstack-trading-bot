# Market Providers

This directory contains market data provider implementations. Each market follows the plugin architecture defined in `base.py`.

## Available Markets

### Kalshi (`kalshi`)

**File:** `kalshi.py`

Prediction market platform for event-based contracts.

**Supported Series:**
- `INXD` - S&P 500 hourly contracts
- `INXH` - S&P 500 daily contracts
- Various political, economic, and weather markets

**Features:**
- RSA-PSS authenticated API
- Rate limiting with exponential backoff
- Real-time orderbook data

## Creating a New Market Provider

### 1. Create Market File

Create `markets/your_market.py`:

```python
"""
Your Market Description
"""

from typing import Any, Dict, List, Optional
from .base import Market


class YourMarket(Market):
    """Your market implementation."""

    def __init__(self, config: Dict[str, Any], client: Any = None):
        super().__init__(config, client)
        # Initialize market-specific settings

    @property
    def name(self) -> str:
        return "your_market"

    async def get_open_markets(
        self,
        series: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
    ) -> List[Dict]:
        """
        Fetch markets from your platform.

        Must return normalized format:
        {
            "ticker": "UNIQUE-ID",
            "title": "Market Title",
            "yes_bid": 45,  # cents
            "yes_ask": 47,  # cents
            "no_bid": 53,   # cents
            "no_ask": 55,   # cents
            "last_price": 46,
            "volume": 1000,
            "volume_24h": 5000,
            "open_interest": 2000,
            "close_time": "2025-01-26T18:00:00Z",
            "status": "open"
        }
        """
        # Fetch from your API
        raw_markets = await self._fetch_from_api(series, limit)

        # Normalize to standard format
        return [self._normalize(m) for m in raw_markets]

    async def get_market(self, ticker: str) -> Dict:
        """Get single market."""
        raw = await self._fetch_single(ticker)
        return self._normalize(raw)

    async def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        order_type: str = "limit",
    ) -> Dict:
        """
        Place order on your platform.

        Must return:
        {
            "order_id": "abc123",
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "price": price_cents,
            "status": "pending",
            "created_time": "2025-01-26T18:00:00Z"
        }
        """
        result = await self._submit_order(ticker, side, action, count, price_cents)
        return self._normalize_order(result)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        return await self._cancel(order_id)

    async def get_positions(self) -> List[Dict]:
        """
        Get open positions.

        Must return:
        [
            {
                "ticker": "MARKET-123",
                "position": 10,  # positive=YES, negative=NO
                "resting_orders_count": 0,
                "realized_pnl": 5.50
            }
        ]
        """
        return await self._fetch_positions()

    async def get_balance(self) -> Dict[str, float]:
        """
        Get account balance.

        Must return:
        {
            "balance": 1000.00,
            "available": 800.00,
            "portfolio_value": 200.00
        }
        """
        return await self._fetch_balance()

    def _normalize(self, raw: Dict) -> Dict:
        """Convert platform-specific format to standard format."""
        # Implement your normalization logic
        return {
            "ticker": raw["id"],
            "title": raw["name"],
            "yes_bid": int(raw["best_bid"] * 100),
            "yes_ask": int(raw["best_ask"] * 100),
            # ... etc
        }
```

### 2. Register Market

Add to `markets/__init__.py`:

```python
from .your_market import YourMarket

MARKET_REGISTRY = {
    "kalshi": KalshiMarket,
    "your_market": YourMarket,  # Add this line
}
```

### 3. Configure in YAML

Add to `config.yaml`:

```yaml
strategies:
  - name: mean_reversion
    markets:
      - platform: your_market  # Use your market
        series: YOUR_SERIES
```

## Market Base Class

The `Market` abstract base class provides:

### Required Methods

- `name` (property): Unique market identifier
- `get_open_markets()`: Fetch available markets
- `get_market()`: Get single market
- `place_order()`: Submit order
- `cancel_order()`: Cancel order
- `get_positions()`: Get open positions
- `get_balance()`: Get account balance

### Optional Methods (with defaults)

- `get_orderbook()`: Fetch orderbook (default: empty)
- `cancel_all_orders()`: Cancel all orders

## Normalized Data Format

All markets must return data in these standard formats:

### Market Data
```python
{
    "ticker": str,           # Unique identifier
    "title": str,            # Human-readable title
    "yes_bid": int,          # Best YES bid (cents)
    "yes_ask": int,          # Best YES ask (cents)
    "no_bid": int,           # Best NO bid (cents)
    "no_ask": int,           # Best NO ask (cents)
    "last_price": int,       # Last trade price (cents)
    "volume": int,           # Total volume
    "volume_24h": int,       # 24-hour volume
    "open_interest": int,    # Open interest
    "close_time": str,       # Market close (ISO format)
    "expiration_time": str,  # Settlement time
    "status": str,           # "open", "closed", "settled"
}
```

### Order Data
```python
{
    "order_id": str,
    "ticker": str,
    "side": str,             # "yes" or "no"
    "action": str,           # "buy" or "sell"
    "count": int,
    "price": int,            # cents
    "status": str,
    "created_time": str,
}
```

### Position Data
```python
{
    "ticker": str,
    "market_ticker": str,
    "position": int,         # positive=YES, negative=NO
    "resting_orders_count": int,
    "total_traded": int,
    "realized_pnl": float,   # dollars
}
```

### Balance Data
```python
{
    "balance": float,        # dollars
    "available": float,      # dollars
    "portfolio_value": float,# dollars
}
```

## Testing Your Market

```python
import asyncio
from markets import load_market

# Create market
market = load_market("your_market", {})

async def test():
    # Test connection
    await market.connect()

    # Test fetching markets
    markets = await market.get_open_markets(series="TEST")
    print(f"Found {len(markets)} markets")

    # Test balance
    balance = await market.get_balance()
    print(f"Balance: ${balance['available']}")

asyncio.run(test())
```
