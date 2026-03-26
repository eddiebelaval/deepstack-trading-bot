# Dae (DeepStack Trading Bot)

Autonomous multi-asset trading bot for Kalshi prediction markets and IBKR traditional markets. Self-governing, self-healing, AI-augmented. Runs 24/7 via macOS launchd.

**LIVE on Kalshi since March 11, 2026.** Paper trading on IBKR.

## Current Status (Mar 25, 2026)

| Metric | Value |
|--------|-------|
| Balance | ~$150 (cash + portfolio) |
| Live trades closed | 111 |
| Paper trades closed | 111 |
| Live PnL | +$6.50 |
| Primary strategy | calibration_edge (80.5% WR live) |
| Phase | SEED ($0-$500) |
| Uptime | Continuous (launchd managed) |

## Architecture

Dae is not a simple trading script. It is a cognitive trading agent with layered intelligence:

```
kalshi_trader/
  main.py                    # Core 60-second trading loop
  kalshi_client.py           # RSA-PSS authenticated Kalshi API
  ibkr_client.py             # IBKR TWS integration (ib_async)
  strategy_manager.py        # Multi-strategy orchestration
  market_governor.py         # Regime detection (5 regimes)
  capital_allocator.py       # Phase-aware Kelly sizing (5 capital phases)
  principle_router.py        # Council of Masters (14 investor archetypes)
  graduation_gate.py         # Paper -> live promotion gates
  performance_tracker.py     # Per-strategy health monitoring
  heartbeat.py               # 3-tier monitoring (free/Haiku/self-repair)
  forward_signal_bridge.py   # PM signals -> stock regime adjustment
  agent.py                   # DaeAgent: 10-tool cognitive agent (read-only)
  engineer.py                # DaeEngineer: self-repair with git deploy
  captains_log.py            # AI narration of bot state
  journal.py                 # SQLite trade journal
  consciousness.py           # CaF integration
  mind/
    memory/lessons.md        # AI self-compacted learnings
    lexicon/                 # 14 master investor profiles
    kernel/                  # Core identity files
    self-awareness/          # Metacognitive reflections
  config.yaml                # Strategy configs, risk params, thresholds
```

## Strategy Arsenal

| Strategy | Platform | Mode | Trades | PnL | Win % |
|----------|----------|------|--------|-----|-------|
| calibration_edge | Kalshi | LIVE | 66 closed, 24 open | -$7.84 | 60.6% |
| calibration_edge | Kalshi | PAPER | 108 closed, 20 open | +$360.62 | 92.6% |
| market_making | Kalshi | LIVE | 39 closed | +$16.41 | 15.4% |
| momentum | Kalshi | LIVE | 3 closed | +$0.16 | 66.7% |
| stock_momentum v2 | IBKR | PAPER | 3 closed, 1 open | -$149.52 | 0.0% |
| crisis_alpha | IBKR | PAPER | 5 open | -- | -- |
| mean_reversion | Kalshi | DISABLED | 3 closed | -$2.23 | 33.3% |
| 12 others | Various | DISABLED | -- | -- | -- |

## Key Systems

### Governance Engine
Autonomous regime detection across 5 states (trending_up/down, mean_reverting, high_vol_choppy, low_vol_calm). Enables/disables strategies based on regime fitness. Council of Masters (Thorp, Taleb, Soros, Buffett, etc.) vote on posture each cycle.

### Capital Allocator
5-phase capital management (SEED through DYNASTY). 30 allocation matrices (5 phases x 6 regimes). Kelly fraction sizing with strategy-fitness feedback loops. Currently in SEED phase.

### Graduation Gates
Paper strategies must prove themselves before going live. Requirements: minimum 30 trades, positive EV, win rate above threshold, regime stability. Each asset class graduates independently.

### Self-Healing (3-Tier)
- **Tier 1** (every cycle, free): P&L breach, consecutive loss, win rate, error rate monitoring
- **Tier 2** (every 30 min, ~$0.01): AI heartbeat via Haiku with standing order execution
- **Tier 3** (on critical failure, ~$0.05): Autonomous code repair via Claude Code CLI with full git deploy pipeline

### Forward Signal Bridge
Prediction market price movements (KXFED, KXCPI, KXBTC) feed into stock regime detection. PM markets move first; the bridge captures this timing advantage.

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Configure
cp .env.example .env  # Add KALSHI_API_KEY_ID
# Place RSA key at ./kalshi_private_key.pem

# Run
python run_bot.py
```

The bot runs as a launchd service (`com.id8labs.deepstack-bot`) for continuous operation.

## Risk Management

- **Kelly Criterion sizing** with per-strategy realized win rates. Capped at 0.05.
- **Circuit breakers**: auto-disable after 5 consecutive losses, 10% drawdown, or <40% win rate over 20 trades.
- **Portfolio halt**: hard stop at min_balance_floor or max_portfolio_drawdown_pct.
- **Emotional firewall**: revenge trade detection, overtrading check, streak detection.
- **Correlation guard**: max 2 positions per series to prevent concentration.
- **Graceful degradation**: IBKR disconnect does not affect Kalshi strategies.

## Monitoring

- **Dashboard**: Next.js control plane at localhost (Command Center, Ops, Intel, Graduation pages)
- **Telegram**: 8 notification hooks (trades, settlements, disables, daily summary, self-repair)
- **Supabase**: Real-time sync of positions, balance, governance decisions
- **Captain's Log**: AI narration streamed to dashboard COMMS panel

## Triad Documents

| Document | Purpose |
|----------|---------|
| `VISION.md` | North star: where Dae is going |
| `SPEC.md` | Living specification: what Dae can do TODAY |
| `BUILDING.md` | Build journal: how Dae got here (18+ phases) |

## API Details

- **Kalshi**: `https://api.elections.kalshi.com/trade-api/v2` (RSA-PSS auth)
- **IBKR**: TWS/Gateway via `ib_async` (TCP connection, port 7497)

## License

Private, id8Labs LLC
