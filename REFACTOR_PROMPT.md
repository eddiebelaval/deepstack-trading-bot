# Kalshi Trading Bot - Multi-Strategy Refactor

## Current State

This bot is a working Kalshi trading system with:
- ✅ RSA authentication with Kalshi API
- ✅ DeepStack integration (Kelly sizing + emotional firewall)
- ✅ Trade journaling (SQLite)
- ✅ One hardcoded strategy: mean-reversion on INXD (S&P 500 hourly)

**Problem:** Everything is tightly coupled. One strategy, one market series, one platform.

## Goal

Refactor into a **plugin architecture** that supports:

1. **Multiple strategies** - Mean-reversion, momentum, arbitrage, etc.
2. **Multiple markets** - Any Kalshi series (INXD, INXH, etc.) + eventually Polymarket
3. **Multiple "personalities"** - Conservative, aggressive, scalper configs
4. **Mix and match** - Run multiple strategies simultaneously on different markets

## Architecture Design

### File Structure
```
kalshi-trading/
├── strategies/
│   ├── base.py              # Abstract base class for all strategies
│   ├── mean_reversion.py    # Current strategy (extract from strategy.py)
│   ├── momentum.py          # NEW: Trend-following strategy
│   └── README.md            # How to add new strategies
├── markets/
│   ├── base.py              # Abstract market interface
│   ├── kalshi.py            # Kalshi implementation (any series)
│   └── README.md            # How to add new markets
├── profiles/
│   ├── conservative.yaml    # Risk-averse config
│   ├── aggressive.yaml      # High-risk high-reward
│   └── scalper.yaml         # High-frequency small gains
├── kalshi_trader/
│   ├── config.py            # Refactored to load YAML profiles
│   ├── strategy_manager.py  # NEW: Orchestrates multiple strategies
│   ├── kalshi_client.py     # (unchanged)
│   ├── deepstack_integration.py  # (unchanged)
│   ├── journal.py           # (unchanged)
│   └── main.py              # Refactored to use strategy_manager
├── run_bot.py               # Updated CLI: --profile=aggressive --strategies=mean_reversion,momentum
└── config.yaml              # Active configuration (which strategies/markets)
```

### Core Interfaces

#### Strategy Base Class
```python
# strategies/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class TradingOpportunity:
    ticker: str
    side: str  # "yes" or "no"
    entry_price_cents: int
    score: float
    reasoning: str
    # ... rest of fields

@dataclass
class ExitSignal:
    ticker: str
    reason: str
    # ... rest

class Strategy(ABC):
    """Base class for all trading strategies."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name."""
        pass
    
    @abstractmethod
    async def scan_opportunities(self, markets: List[dict]) -> List[TradingOpportunity]:
        """Find trading opportunities in given markets."""
        pass
    
    @abstractmethod
    async def check_exit(self, position: dict, current_price: int) -> Optional[ExitSignal]:
        """Check if position should be exited."""
        pass
```

#### Market Base Class
```python
# markets/base.py
from abc import ABC, abstractmethod
from typing import List, Dict

class Market(ABC):
    """Base class for market data providers."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @abstractmethod
    async def get_open_markets(self, filters: dict) -> List[dict]:
        """Fetch open markets matching filters."""
        pass
    
    @abstractmethod
    async def place_order(self, order: dict) -> dict:
        """Place an order."""
        pass
```

### Configuration

**config.yaml** (runtime configuration):
```yaml
profile: aggressive  # Which profile to use

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
    enabled: false
    markets:
      - platform: kalshi
        series: INXH  # S&P 500 daily
    config:
      lookback_hours: 24
      momentum_threshold: 0.15
  
  - name: combinatorial_arbitrage
    enabled: true
    markets:
      - platform: kalshi
        series: "*"  # Scan all markets
      - platform: polymarket
        series: "*"  # When Polymarket integration ready
    config:
      min_profit_cents: 2  # Minimum guaranteed profit to execute
      max_exposure_per_arb: 100  # Max capital per arbitrage set
      relationship_types:
        - mutually_exclusive  # Outcomes that should sum to $1
        - parent_child  # Related markets with dependencies

risk:
  max_position_size: 50
  daily_loss_limit: 100
  kelly_fraction: 0.5
```

**profiles/aggressive.yaml**:
```yaml
name: aggressive
risk:
  kelly_fraction: 0.75
  max_position_size: 100
  daily_loss_limit: 200
```

### Strategy Manager

```python
# kalshi_trader/strategy_manager.py
class StrategyManager:
    """Orchestrates multiple strategies across multiple markets."""
    
    def __init__(self, config: dict, strategies: List[Strategy], markets: List[Market]):
        self.config = config
        self.strategies = strategies
        self.markets = markets
    
    async def scan_all_opportunities(self) -> List[TradingOpportunity]:
        """Scan all enabled strategies across all markets."""
        opportunities = []
        for strategy in self.strategies:
            for market in self.markets:
                markets_data = await market.get_open_markets(...)
                opps = await strategy.scan_opportunities(markets_data)
                opportunities.extend(opps)
        return opportunities
    
    async def rank_opportunities(self, opportunities: List[TradingOpportunity]) -> List[TradingOpportunity]:
        """Rank opportunities by score, apply portfolio constraints."""
        # Sort by score
        # Apply diversification rules
        # Return top N
        pass
```

## Implementation Plan

### Phase 1: Extract & Modularize (Foundation)
1. Create `strategies/base.py` with Strategy ABC
2. Extract current mean-reversion logic from `strategy.py` → `strategies/mean_reversion.py`
3. Create `markets/base.py` with Market ABC
4. Create `markets/kalshi.py` wrapping existing kalshi_client
5. Update `config.py` to load YAML instead of env vars

### Phase 2: Strategy Manager (Orchestration)
1. Create `kalshi_trader/strategy_manager.py`
2. Update `main.py` to use StrategyManager instead of direct strategy
3. Test with single strategy (mean-reversion) to ensure parity

### Phase 3: Multi-Strategy Support
1. Implement `strategies/momentum.py` as second strategy
2. Implement `strategies/combinatorial_arbitrage.py` as third strategy (see Research section)
3. Create `config.yaml` with all three strategies
4. Update CLI (`run_bot.py`) to accept `--strategies` flag
5. Test running multiple strategies simultaneously

### Phase 4: Profiles
1. Create `profiles/` directory with YAML templates
2. Update config loader to merge profile + config.yaml
3. Test different profiles (conservative, aggressive, scalper)

### Phase 5: Documentation & Polish
1. Add `strategies/README.md` - how to build custom strategies
2. Add `markets/README.md` - how to add new platforms
3. Update main README.md with new architecture
4. Add examples/templates

## Testing Strategy

- **Unit tests**: Each strategy in isolation
- **Integration test**: StrategyManager with mock market data
- **Live test**: Paper trading with $0 balance (scan-only mode)
- **Real money**: Small position sizes first

## Constraints

- **Preserve existing functionality**: Mean-reversion on INXD must work exactly as before
- **Backward compatible**: Old .env config should still work (with deprecation warning)
- **DeepStack integration**: Keep Kelly + emotional firewall working
- **No breaking changes**: Existing trade_journal.db should still work

## Success Criteria

1. ✅ Can run multiple strategies simultaneously
2. ✅ Can add new strategy by creating one file in `strategies/`
3. ✅ Can switch between profiles with `--profile=name`
4. ✅ All existing tests pass
5. ✅ Clear documentation for extending system

## Questions to Consider

1. **Strategy conflicts**: What if two strategies want to trade the same ticker opposite sides?
2. **Risk allocation**: How to split max position size across multiple strategies?
3. **Performance**: Does scanning all strategies cause API rate limits?
4. **State management**: Where do strategies store their internal state (e.g., momentum lookback)?

## Deliverables

1. Refactored codebase with plugin architecture
2. Three working strategies:
   - Mean-reversion (existing, refactored)
   - Momentum (new)
   - Combinatorial arbitrage (new, research-backed)
3. Three working profiles (conservative, aggressive, scalper)
4. Updated documentation
5. Migration guide from old to new config

---

## Research: Combinatorial Arbitrage Strategy

**Paper:** "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets" (arXiv:2508.03474)

**Key Findings:**
- $40 million in realized arbitrage profit extracted from Polymarket
- Two types of arbitrage exist:
  1. **Market Rebalancing Arbitrage** — Within single markets (what mean-reversion does)
  2. **Combinatorial Arbitrage** — Across related markets where outcomes should sum to $1 but don't

**Strategy Concept:**
Related markets/conditions on prediction platforms should have prices that sum to $1 (representing 100% probability). When they don't, you can:
- Buy all outcomes for <$1 total → guaranteed profit
- Sell all outcomes for >$1 total → guaranteed profit

**Example:**
- Market A: "Trump wins" at 52¢
- Market B: "Biden wins" at 49¢
- Total: $1.01 → Sell both for guaranteed 1¢ profit per contract

**Technical Challenge:**
Naive comparison across all markets = O(2^(n+m)) complexity (exponential blowup)

**Solution (from paper):**
Heuristic-driven reduction:
- Filter by **timeliness** (only compare active, liquid markets)
- Filter by **topical similarity** (only compare related topics)
- Filter by **combinatorial relationships** (parent/child markets, mutually exclusive outcomes)

**Implementation for `strategies/combinatorial_arbitrage.py`:**
1. Maintain graph of market relationships (parent/child, mutually exclusive)
2. Continuously scan related market sets for pricing inconsistencies
3. Execute simultaneous buy/sell across related markets when sum ≠ $1
4. Use heuristics to limit search space to tractable size

**Profit Potential:**
If $40M was extracted historically, the strategy has proven edge. Modern implementation with fast execution could capture these opportunities before manual arbitrageurs.

---

**Current codebase:** `./`

Please implement this refactor maintaining all existing functionality while enabling the modular multi-strategy architecture described above.
