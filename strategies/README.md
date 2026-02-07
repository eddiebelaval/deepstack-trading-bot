# Trading Strategies

This directory contains trading strategy implementations. Each strategy follows the plugin architecture defined in `base.py`.

## Available Strategies

### Mean Reversion (`mean_reversion`)

**File:** `mean_reversion.py`

Contrarian strategy that profits from price reversion to 50 cents (maximum uncertainty).

**Configuration:**
```yaml
name: mean_reversion
config:
  price_floor_cents: 45      # Minimum YES price to consider
  price_ceiling_cents: 55    # Maximum YES price to consider
  take_profit_cents: 8       # Exit with profit at +8c
  stop_loss_cents: 5         # Exit with loss at -5c
  min_volume: 100            # Minimum market volume
  min_score: 30              # Minimum opportunity score
```

**Logic:**
- When YES price < 50c: Buy YES (market undervalues)
- When YES price > 50c: Buy NO (market overvalues)
- Profit from reversion toward 50c

**Expected Value:**
- Win rate: 60%
- EV = (0.60 * 8) - (0.40 * 5) = +2.8c per contract

### Momentum (Coming Soon)

Trend-following strategy based on price momentum.

## Creating a New Strategy

### 1. Create Strategy File

Create `strategies/your_strategy.py`:

```python
"""
Your Strategy Description
"""

from typing import Any, Dict, List, Optional
from .base import Strategy, TradingOpportunity, ExitSignal


class YourStrategy(Strategy):
    """Your strategy implementation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Initialize strategy-specific parameters
        self.your_param = config.get("your_param", default_value)

    @property
    def name(self) -> str:
        return "your_strategy"

    @property
    def description(self) -> str:
        return "Description of your strategy"

    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Implement your opportunity scanning logic.

        Args:
            markets: List of market data dicts
            existing_positions: Tickers to skip

        Returns:
            List of TradingOpportunity objects
        """
        opportunities = []

        for market in markets:
            # Your analysis logic here
            if self._is_opportunity(market):
                opp = TradingOpportunity(
                    ticker=market["ticker"],
                    title=market["title"],
                    side="yes",  # or "no"
                    entry_price_cents=50,
                    current_yes_price=market.get("yes_bid", 50),
                    current_no_price=100 - market.get("yes_bid", 50),
                    volume=market.get("volume", 0),
                    score=75.0,
                    reasoning="Your reasoning",
                    expected_profit_cents=self.take_profit,
                    max_loss_cents=self.stop_loss,
                    strategy_name=self.name,
                )
                opportunities.append(opp)

        return sorted(opportunities, key=lambda x: x.score, reverse=True)

    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """
        Implement your exit logic.
        """
        entry_price = position.get("entry_price", 50)
        pnl = current_price - entry_price

        # Take profit
        if pnl >= self.take_profit:
            return ExitSignal(
                should_exit=True,
                reason=f"Take profit: +{pnl}c",
                exit_type="take_profit",
                current_price_cents=current_price,
                pnl_cents=pnl,
            )

        # Stop loss
        if pnl <= -self.stop_loss:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss: {pnl}c",
                exit_type="stop_loss",
                current_price_cents=current_price,
                pnl_cents=pnl,
            )

        # Hold
        return ExitSignal(
            should_exit=False,
            reason="Holding",
            exit_type="hold",
            current_price_cents=current_price,
            pnl_cents=pnl,
        )

    def get_historical_stats(self) -> Dict[str, float]:
        """Return statistics for Kelly sizing."""
        return {
            "win_rate": 0.55,
            "avg_win_cents": float(self.take_profit),
            "avg_loss_cents": float(self.stop_loss),
        }
```

### 2. Register Strategy

Add to `strategies/__init__.py`:

```python
from .your_strategy import YourStrategy

STRATEGY_REGISTRY = {
    "mean_reversion": MeanReversionStrategy,
    "your_strategy": YourStrategy,  # Add this line
}
```

### 3. Configure in YAML

Add to `config.yaml`:

```yaml
strategies:
  - name: your_strategy
    enabled: true
    markets:
      - platform: kalshi
        series: INXD
    config:
      your_param: value
      take_profit_cents: 8
      stop_loss_cents: 5
```

## Strategy Base Class

The `Strategy` abstract base class provides:

### Required Methods

- `name` (property): Unique strategy identifier
- `scan_opportunities()`: Find trading opportunities
- `check_exit()`: Determine if position should exit

### Optional Methods (with defaults)

- `description` (property): Human-readable description
- `get_historical_stats()`: Statistics for Kelly sizing
- `calculate_edge()`: Calculate theoretical edge
- `get_exit_price()`: Calculate limit order exit price
- `validate_config()`: Validate configuration

### Data Classes

**TradingOpportunity:**
```python
@dataclass
class TradingOpportunity:
    ticker: str
    title: str
    side: str  # "yes" or "no"
    entry_price_cents: int
    current_yes_price: int
    current_no_price: int
    volume: int
    score: float  # 0-100
    reasoning: str
    expected_profit_cents: int
    max_loss_cents: int
    strategy_name: str
    metadata: Dict[str, Any]
```

**ExitSignal:**
```python
@dataclass
class ExitSignal:
    should_exit: bool
    reason: str
    exit_type: str  # "take_profit", "stop_loss", "expiry", "manual", "hold"
    current_price_cents: int
    pnl_cents: int
    urgency: float  # 0-1
```

## Testing Your Strategy

```python
import asyncio
from strategies import load_strategy

# Create strategy
config = {"take_profit_cents": 10, "stop_loss_cents": 5}
strategy = load_strategy("your_strategy", config)

# Test with mock data
markets = [
    {"ticker": "TEST-123", "title": "Test Market", "yes_bid": 45, "yes_ask": 47, "volume": 500, "status": "open"}
]

async def test():
    opps = await strategy.scan_opportunities(markets)
    for opp in opps:
        print(f"{opp.ticker}: {opp.side} @ {opp.entry_price_cents}c (score: {opp.score})")

asyncio.run(test())
```
