# Kalshi Trading Bot

Automated trading bot for Kalshi prediction markets using a multi-strategy plugin architecture with DeepStack risk management.

## Features

- **Multi-Strategy Plugin Architecture**: Easily add new trading strategies
- **Mean-Reversion Strategy**: Trades markets near 50 cents (maximum uncertainty)
- **Momentum Strategy**: Trend-following based on price momentum
- **Kelly Criterion Sizing**: Optimal position sizing with safety caps
- **Emotional Firewall**: Prevents revenge trading, overtrading, and loss chasing
- **Trade Journal**: SQLite persistence for analysis and audit
- **YAML Configuration**: Profiles for conservative, aggressive, and scalper modes
- **Graceful Shutdown**: Cancels open orders on exit

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file:

```bash
KALSHI_API_KEY_ID=your_api_key_id_here
KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem
```

### 3. Add Your Private Key

Place your Kalshi RSA private key at `./kalshi_private_key.pem`

### 4. Run the Bot

```bash
# Legacy mode (single strategy, backward compatible)
python run_bot.py

# Multi-strategy mode
python run_bot.py --multi

# With a profile
python run_bot.py --profile=aggressive

# With specific strategies
python run_bot.py --strategies=mean_reversion,momentum
```

## CLI Options

```bash
python run_bot.py --help

Options:
  --multi               Enable multi-strategy mode
  --profile NAME        Load profile (conservative, aggressive, scalper)
  --strategies LIST     Comma-separated strategies to enable
  --config PATH         Path to config.yaml
  --list-strategies     Show available strategies
  --list-profiles       Show available profiles
  --dry-run             Scan but don't trade
  -v, --verbose         Debug logging
```

## Available Strategies

| Strategy | Description | EV | Win Rate |
|----------|-------------|------|----------|
| `mean_reversion` | Buy near 50c, profit from reversion | +2.8c | 60% |
| `momentum` | Follow trends based on price momentum | +2.8c | 55% |

List strategies: `python run_bot.py --list-strategies`

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_API_KEY_ID` | (required) | Kalshi API key ID |
| `KALSHI_PRIVATE_KEY_PATH` | `./kalshi_private_key.pem` | RSA private key path |
| `KALSHI_MAX_POSITION` | `50` | Max position size ($) |
| `KALSHI_DAILY_LOSS_LIMIT` | `100` | Daily loss limit ($) |

### YAML Configuration

Edit `config.yaml` for detailed control:

```yaml
profile: aggressive  # Or: conservative, scalper

strategies:
  - name: mean_reversion
    enabled: true
    markets:
      - platform: kalshi
        series: INXD
    config:
      price_floor_cents: 45
      price_ceiling_cents: 55
      take_profit_cents: 8
      stop_loss_cents: 5

  - name: momentum
    enabled: true
    markets:
      - platform: kalshi
        series: INXD
    config:
      momentum_threshold: 0.03
      take_profit_cents: 10
      stop_loss_cents: 6

risk:
  max_position_size: 100
  daily_loss_limit: 200
  kelly_fraction: 0.75
```

## Profiles

| Profile | Risk Level | Max Position | Kelly | Description |
|---------|------------|--------------|-------|-------------|
| `conservative` | Low | $25 | 25% | Capital preservation |
| `default` | Medium | $50 | 50% | Balanced approach |
| `aggressive` | High | $100 | 75% | Growth focused |
| `scalper` | Medium | $75 | 50% | Quick trades |

List profiles: `python run_bot.py --list-profiles`

## Architecture

```
kalshi-trading/
├── strategies/               # Strategy plugins
│   ├── base.py              # Abstract Strategy class
│   ├── mean_reversion.py    # Mean-reversion strategy
│   ├── momentum.py          # Momentum strategy
│   └── README.md            # How to add strategies
├── markets/                  # Market adapters
│   ├── base.py              # Abstract Market class
│   ├── kalshi.py            # Kalshi implementation
│   └── README.md            # How to add markets
├── profiles/                 # YAML risk profiles
│   ├── conservative.yaml
│   ├── aggressive.yaml
│   └── scalper.yaml
├── kalshi_trader/
│   ├── config.py            # Configuration loading
│   ├── strategy_manager.py  # Multi-strategy orchestration
│   ├── kalshi_client.py     # RSA-authenticated API
│   ├── deepstack_integration.py
│   ├── journal.py           # Trade logging
│   └── main.py              # Trading loop
├── config.yaml              # Main configuration
├── run_bot.py               # CLI entry point
└── requirements.txt
```

## Adding a New Strategy

1. Create `strategies/your_strategy.py`:

```python
from strategies.base import Strategy, TradingOpportunity, ExitSignal

class YourStrategy(Strategy):
    @property
    def name(self) -> str:
        return "your_strategy"

    async def scan_opportunities(self, markets, existing_positions=None):
        # Your logic here
        return [TradingOpportunity(...)]

    async def check_exit(self, position, current_price, market_data=None):
        # Your exit logic
        return ExitSignal(...)
```

2. Register in `strategies/__init__.py`:

```python
from .your_strategy import YourStrategy
STRATEGY_REGISTRY["your_strategy"] = YourStrategy
```

3. Configure in `config.yaml`:

```yaml
strategies:
  - name: your_strategy
    enabled: true
    markets:
      - platform: kalshi
        series: INXD
```

See `strategies/README.md` for detailed guide.

## Risk Management

The bot integrates with DeepStack's risk management:

1. **Kelly Position Sizer**: Calculates optimal position sizes
2. **Emotional Firewall**: Blocks trades when:
   - Trading within 30 min of a loss (revenge trading)
   - More than 3 trades/hour (overtrading)
   - 5+ consecutive losses (loss streak)
   - Position size increase after loss (loss chasing)

## Strategy Conflict Resolution

When multiple strategies signal on the same ticker:

- **Same direction**: Higher score wins
- **Opposite directions**: Higher score wins (last strategy rule)

Risk allocation: Position size is split evenly across active strategies.

## Expected Value

Mean-reversion strategy:
```
EV = (0.60 x 8) - (0.40 x 5) = +2.8c per contract
```

Momentum strategy:
```
EV = (0.55 x 10) - (0.45 x 6) = +2.8c per contract
```

## DeepStack Dependency

Requires DeepStack at:
```
/Users/eddiebelaval/Development/id8/products/deepstack
```

Path is configured in `kalshi_trader/deepstack_integration.py`.

## API Details

- **Base URL**: `https://api.elections.kalshi.com/trade-api/v2`
- **Authentication**: RSA-PSS signatures with DIGEST_LENGTH salt
- **Rate Limit**: 60 requests/minute

## License

Private - ID8 Labs
