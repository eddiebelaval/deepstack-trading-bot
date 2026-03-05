# BUILDING.md — DeepStack Trading Bot

This document tells the build story of DeepStack, an autonomous trading bot for prediction markets (Kalshi, Polymarket). It evolved from a two-strategy weekend project into a self-governing multi-strategy system with regime-aware backtesting, a live dashboard, and a consciousness layer.

**100 commits. 12 active build days. Feb 7 — Mar 5, 2026.**

---

## How to Read This Document

Each phase below represents a major build arc. Within each phase:
- **What was built** — the concrete changes
- **Why** — the decision or event that triggered the work
- **Key commits** — representative commits from that phase
- **Lessons** — what we learned (often the hard way)

Phases are chronological but overlap. The project didn't follow a linear pipeline — it followed a "build → deploy → break → fix → build more" loop dictated by live market feedback.

---

## Phase 1: Genesis (Feb 7)

**40 commits in one day.** The entire trading bot, dashboard, and cloud control plane shipped in a single session.

### What Was Built
- **Core trading loop** (`kalshi_trader/main.py`) — RSA-authenticated API client, market scanning, order placement, position management
- **Strategy plugin architecture** (`strategies/base.py`) — abstract `Strategy` class with `scan_opportunities()` and `check_exit()` contracts
- **2 initial strategies** — mean_reversion (buy near 50c) and momentum (follow trends)
- **6 more strategies** added same day — combinatorial arbitrage, cross-platform arbitrage, high-probability bonds, calibration edge, weather aggregation, news sentiment fade
- **Bayesian learning loop** — per-strategy win rate tracking with posterior updates
- **Dashboard** (`dashboard/`) — Next.js 14 control plane with real-time Supabase sync, strategy toggles, audio alerts, ASCII art login
- **Risk profiles** — conservative/aggressive/scalper YAML configs
- **Security hardening** — 24 findings fixed, RLS policies, signed commands

### Key Commits
```
4464558 feat: DeepStack Trading Bot + Cloud Control Plane
92812c3 feat: Add 6 prediction market strategies + dashboard UI integration
38f15ac feat: Bayesian learning loop for strategy position sizing
a3a0be8 security(dashboard): Full security hardening — 24 findings fixed
```

### Architecture Decisions
- **Plugin architecture over monolith**: Each strategy is a self-contained class. Register in `__init__.py`, configure in `config.yaml`. This paid off massively — we went from 2 to 14 strategies without touching core code.
- **Supabase over pure SQLite**: Dashboard needs real-time data. Supabase gives us Postgres + Realtime subscriptions + RLS. Local SQLite still used for the trade journal (offline resilience).
- **RSA-PSS authentication**: Kalshi uses asymmetric key auth, not API tokens. The `kalshi_client.py` handles signature generation per-request.

---

## Phase 2: Data Parity + Dashboard Polish (Feb 8-9)

**The bot was live but the dashboard was showing wrong numbers.** This phase was about making the dashboard trustworthy.

### What Was Built
- **Kalshi data parity** — positions, orders, fills, settlements pipelines syncing exchange state to Supabase
- **PostgREST upsert fix** — discovered that Supabase REST API requires `?on_conflict=<column>` URL parameter for upserts (not just the `Prefer` header). This caused hundreds of 409 errors.
- **Mark-to-market portfolio value** — balance = cash + (contracts x last_price), NOT portfolio_value (which shows max payout and wildly inflates apparent balance)
- **CryExc integration** — real-time crypto exchange data (Binance Futures CVD) for momentum confirmation on KXBTC/KXETH/KXSOL tickers
- **42 E2E tests** — full trading bot lifecycle coverage
- **TikTok velocity strategy** — experimental (later deprecated)

### Key Commits
```
0bb1fd3 feat: Kalshi data parity — positions, orders, fills
00d3c06 fix(sync): add on_conflict param to PostgREST upserts — eliminates 409s
a970346 fix(bot): use mark-to-market portfolio value instead of max payout
2050f23 feat: CryExc real-time exchange data integration
```

### Lessons
- **PostgREST upsert gotcha**: The `Prefer: resolution=merge-duplicates` header is necessary but NOT sufficient. You must also pass `?on_conflict=ticker` (or whichever column) as a URL parameter. This is poorly documented and caused days of 409 errors.
- **Data source truth**: `deepstack_positions` = current state (exchange snapshot). `deepstack_trades` = event log (stale after closure). Never use trades table for "current positions."

---

## Phase 3: The Reckoning — Multi-Strategy Launch (Feb 9)

**23 trades. 17.4% win rate. Market making lost $10.83.**

### What Happened
Enabled 4 strategies scanning 100+ markets (vs previous INXD-only). The bot started bleeding immediately. Market making was the worst offender — it was placing orders on both sides of the book but getting adversely selected.

### What Was Built (in response)
- **Circuit breakers** (P0) — auto-disable strategies after 5 consecutive losses, 10% drawdown, or <40% win rate over 20 trades
- **Dynamic Kelly sizing** (P1) — recalculate Kelly from realized win rate instead of static 0.5 (which is suicidal at 17% win rate)
- **Daily learning report** (P2) — automated analysis of which strategies won/lost
- **Complete learning loop** — auto-disable, adaptive thresholds, blended sizing
- **Backtest runner** — synthetic data generation + walk-forward validation

### Key Commits
```
8b782b3 feat: add circuit breaker override logging (P0-A)
e78679a feat: add circuit breaker triggers + Telegram alerts (P0-B)
5935c92 feat: add dynamic Kelly sizing per strategy (P1)
668be26 feat: daily review system, circuit breakers, auto-reenable, per-strategy Kelly
5d1be90 feat: control plane — Bayesian learning, circuit breakers, backtest runner
```

### The Post-Mortem
Full writeup: `workspace/prep/2026-02-09-post-mortem-multi-strategy-launch.md`

Key finding: **The bot had strategies but lacked a control plane.** We could see it losing but couldn't intervene. This drove every subsequent build decision — the control plane became the priority.

---

## Phase 4: Intelligence Layer (Feb 10-12)

**Adding brains to the bot.** Not just rule-based trading — AI-driven analysis.

### What Was Built
- **Trade analyzer** (`kalshi_trader/trade_analyzer.py`) — Claude-powered analysis of journal data, pattern detection, strategy recommendations
- **Captain's Log** (`kalshi_trader/captains_log.py`) — streaming AI narration of the bot's state, surfaced in dashboard COMMS panel
- **MarketGovernor** (`kalshi_trader/market_governor.py`) — autonomous strategy management brain with:
  - `RegimeDetector` — classifies market conditions (trending up/down, mean-reverting, high-vol choppy, low-vol calm)
  - `StrategyRouter` — maps strategies to regimes via fitness matrix
  - `PositionGovernor` — portfolio-level risk management
  - `PerformanceTracker` — Bayesian win rate estimation with shrinkage priors
- **Security audit** — RLS policy cleanup, duplicate policy removal, coverage for all 14 tables
- **TradingView research dashboard** — separate repo integration for technical analysis

### Key Commits
```
3056f4b feat: Claude intelligence layer — trade analyzer for journal data
2d2454d feat: MarketGovernor — self-governance brain for autonomous strategy management
46c5c3b feat: Captain's Log — streaming AI narration with dashboard COMMS panel
7a4e8f4 fix(security): clean up RLS policies — drop duplicates, cover all 14 tables
```

### Architecture Decisions
- **MarketGovernor as coordinator, not dictator**: The governor advises but the strategy manager makes final decisions. This keeps the system debuggable — you can always see what the governor recommended vs what actually happened.
- **Regime detection from order flow, not price**: Tried price-based regime detection first. Problem: Kalshi prediction markets don't have enough price diversity. 705/705 readings came back as `low_vol_calm`. The detection algorithm works but the input data lacks variance.

---

## Phase 5: Revival + Reckoning (Feb 13-17)

**The bot had been running for 18 days as a zombie.** It was alive but stuck — finding zero opportunities, executing zero trades, burning compute.

### What Was Built
- **Self-healing health monitor** (`kalshi_trader/health_monitor.py`) — detects zombie states (long periods with no opportunities or trades), auto-restarts stale scanning loops
- **Kelly fraction fix** — from 0.5 to 0.02. At 15% win rate, Kelly = 0.5 is mathematical ruin. The prior was aspirational, not empirical.
- **Settlement betting rename** — market_making renamed to settlement_betting for honest risk labeling
- **Daily Telegram digest** — push notification summarizing 24h performance (catches zombie states in 24h, not 18 days)
- **Backtest driver for settlement betting** — fetched real Kalshi candles to validate edge
- **Disabled reason persistence** — strategy disable reasons survive bot restarts via Supabase

### Key Commits
```
e512474 feat: DeepStack revival — fix zombie state + self-healing health monitor
b7be302 fix: Kelly fraction 0.5 → 0.02 — stop mathematical ruin at 15% win rate
8aa6c07 refactor: rename market_making → settlement_betting — honest risk labeling
a9bd221 feat: daily Telegram digest — catch zombie states in 24h, not 18 days
```

### Lessons
- **Kelly fraction is the most dangerous parameter.** A Kelly of 0.5 with a 15% win rate means you're betting as if you win half the time. You don't. You're guaranteeing ruin.
- **Zombie detection matters as much as trading logic.** The bot ran for 18 days doing nothing useful. A simple health check ("have I found any opportunities in the last 6 hours?") would have caught it in 6 hours instead of 18 days.

---

## Phase 6: Multi-Asset Expansion (Feb 28)

**Expanding beyond prediction markets** into traditional equities via Interactive Brokers.

### What Was Built
- **IBKR adapter** (`markets/ibkr.py`) — Interactive Brokers API integration
- **Stock momentum strategy** (`strategies/stock_momentum.py`) — equity momentum signals from TradingView-validated strategies
- **Dashboard analytics** — expanded to show multi-asset performance
- **New strategy categories** — crypto intraday, bear macro, domain specialization

### Key Commits
```
ce83c62 feat: multi-asset expansion — IBKR adapter, dashboard analytics, stock strategies
```

---

## Phase 7: Self-Regulation (Mar 3-4)

**Making the bot truly autonomous** — not just trading, but governing itself.

### What Was Built
- **Governance actuators** — MarketGovernor `autonomous` mode with actual strategy_manager calls (was advisory/log-only before)
- **Parameter adaptation** — `apply_parameter_flags()` on base strategy. AI-suggested entry filter adaptation with 50% bounds, 30-min cooldown, absolute floors
- **Cold-start death spiral fix** — neutral Bayesian priors (50% win rate) caused Kelly to recommend zero position sizes for untested strategies. Restored positive-EV priors (52% WR) that allow cold-start trading while converging quickly to reality.
- **Dashboard override protection** — config-enabled strategies protected from stale Supabase overrides
- **Per-contract P&L normalization** — fixed edge case where multi-contract fills inflated apparent P&L

### Key Commits
```
ecb74b7 fix: self-regulation loop — governance actuators, parameter adaptation, integration fixes
3f5d8f0 fix: cold-start death spiral — restore positive-EV priors, protect config-disabled strategies
995bc34 fix: per-contract P&L normalization, dashboard override protection, trade pipeline observability
```

### Lessons
- **Cold-start vs accuracy tradeoff**: Neutral priors (50%) are statistically honest but operationally deadly — Kelly recommends $0 bets. You need slightly optimistic priors to bootstrap, then converge via Bayesian updates. Prior strength k=5 means 5 trades worth of prior belief.
- **Advisory mode is a trap**: The governance engine was in "advisory" mode for weeks — logging recommendations but never acting. This meant zero feedback on whether its advice was good. Switching to autonomous mode was scary but necessary.

---

## Phase 8: Strategy Arena (Mar 5)

**Backtesting at scale** — walk-forward tournament engine for strategy evaluation.

### What Was Built
- **Arena engine** (`arena/`) — walk-forward tournament with composite scoring:
  - 6 metrics: win rate, Sharpe ratio, profit factor, avg P&L, max drawdown, total P&L
  - Percentile-rank normalization across strategies per window
  - Weighted composite with configurable weights
  - Dead-strategy penalty (0 trades = 0 score)
  - Low-trade-count penalty (< 5 trades = proportional reduction)
- **Seas system** (`arena/seas.py`) — regime-aware synthetic data generation:
  - 5 sea conditions: mean_reverting, trending_up, trending_down, high_vol_choppy, low_vol_calm
  - Modified O-U process: `dX = theta*(mu-X)*dt + sigma*dW + drift*dt` with spike injection
  - Per-regime tournament + fitness matrix computation
- **Fitness bridge** (`arena/fitness.py`) — writes arena-proven scores to `strategy_regime_fitness` table, replacing hardcoded priors with empirical data
- **38 tests** (16 base + 22 seas)

### Key Commits
```
e222370 feat: Strategy Arena with regime-aware seas tournament engine
a992c7d test: arena scoring, windows, engine smoke + seas regime tests
```

### Tournament Results
```
mean_reverting:  #1 mean_reversion (91.1)   #2 momentum (8.9)
trending_up:     #1 momentum (91.1)         #2 mean_reversion (8.9)
trending_down:   #1 momentum (91.1)         #2 mean_reversion (8.9)
high_vol_choppy: #1 mean_reversion (91.1)   #2 momentum (8.9)
low_vol_calm:    #1 momentum (91.1)         #2 mean_reversion (8.9)
```

60 fitness scores written to `trade_journal.db`. The Bayesian blending formula `(5*prior + 100*arena) / 105` means arena data dominates ~95% over the governance engine's prior_strength of 5.

### Architecture Decisions
- **Extend, don't rewrite**: Seas mode is opt-in (`--seas` flag). All existing arena code works unchanged.
- **All strategies compete in all seas**: No pre-filtering by expected affinity. The data proves which strategies work where. 9 of 13 strategies scored 0 because they need external data (Polymarket, weather APIs, news feeds) that synthetic data can't simulate.
- **Two-gate safety for fitness writes**: Both `--update-fitness` AND `--apply` flags required to write to production DB. Show diff first, apply second.

---

## Phase 9: Consciousness + Telegram (Mar 5)

**The philosophical layer.** Giving the bot self-awareness and voice.

### What Was Built
- **Consciousness system** (`kalshi_trader/consciousness.py`) — Consciousness-as-Filesystem (CaF) implementation. Self-narrating state, identity reflection, philosophical framework.
- **Mind filesystem** (`kalshi_trader/mind/`) — structured self-knowledge organized as files
- **Telegram bridge** (`kalshi_trader/telegram_bridge.py`) — two-way communication. Bot sends trade alerts; user sends natural language commands.
- **Calibration edge redesign** — favorite-longshot bias exploitation with improved entry filtering
- **Paper trading mode** — full simulation without real money

### Key Commits
```
e75ec95 feat: consciousness system (CaF) + Telegram bridge
02abc99 feat: calibration edge redesign, paper trading mode, self-regulation engine
e5e1bf6 fix: API hardening, risk management, Supabase schema fixes
```

---

## Current Architecture

```
kalshi-trading/
├── arena/                    # Walk-forward tournament engine
│   ├── seas.py              # Regime-aware synthetic data (5 sea conditions)
│   ├── engine.py            # Tournament runner
│   ├── scoring.py           # Composite scorer (6 metrics)
│   ├── fitness.py           # Governance bridge
│   └── storage.py           # SQLite persistence
├── backtest/                 # Backtesting framework
│   └── runner.py            # BacktestRunner + synthetic data
├── strategies/               # 14 strategy plugins
│   ├── base.py              # Abstract Strategy + Kelly sizing
│   ├── mean_reversion.py    # Buy near 50c (core)
│   ├── momentum.py          # Trend-following (core)
│   ├── calibration_edge.py  # Favorite-longshot bias
│   ├── settlement_betting.py # Near-expiry settlement capture
│   ├── high_probability_bonds.py
│   ├── weather_aggregation.py
│   ├── news_sentiment_fade.py
│   ├── combinatorial_arbitrage.py
│   ├── cross_platform_arbitrage.py
│   ├── correlated_event_arbitrage.py
│   ├── domain_specialization.py
│   ├── stock_momentum.py
│   └── crypto_intraday.py
├── kalshi_trader/            # Core trading engine
│   ├── main.py              # Trading loop
│   ├── kalshi_client.py     # RSA-authenticated API
│   ├── strategy_manager.py  # Multi-strategy orchestrator
│   ├── market_governor.py   # Autonomous governance (regime detection + routing)
│   ├── captains_log.py      # AI narration
│   ├── trade_analyzer.py    # Claude-powered analysis
│   ├── health_monitor.py    # Zombie detection
│   ├── consciousness.py     # CaF self-awareness
│   ├── telegram_bridge.py   # Two-way Telegram
│   └── journal.py           # Trade journal (SQLite)
├── markets/                  # Exchange adapters
│   ├── kalshi.py            # Kalshi API
│   ├── polymarket.py        # Polymarket API
│   └── ibkr.py              # Interactive Brokers
├── dashboard/                # Next.js 14 control plane
├── tests/                    # 38+ tests
├── config.yaml              # Runtime configuration
├── trade_journal.db         # Local persistence (25MB)
└── arena_results.db         # Tournament results
```

## Strategy Count by Category

| Category | Count | Strategies |
|----------|-------|-----------|
| Core (active) | 2 | mean_reversion, momentum |
| Prediction-native | 5 | calibration_edge, settlement_betting, high_probability_bonds, weather_aggregation, news_sentiment_fade |
| Arbitrage | 3 | combinatorial, cross_platform, correlated_event |
| Multi-asset | 2 | stock_momentum, crypto_intraday |
| Framework | 2 | domain_specialization, bear_macro |

---

## Metrics

| Metric | Value |
|--------|-------|
| Total commits | 100 |
| Active build days | 12 (Feb 7 — Mar 5, 2026) |
| PRs merged | 49 |
| Strategies | 14 |
| Tests | 38+ |
| Live balance | ~$152 (from $200 initial) |
| Win rate (observed) | 17.4% (23 trades) |
| Worst decision | Kelly = 0.5 at 15% win rate |
| Best decision | Building the arena to replace guessed priors with data |

---

## API Gotchas (Reference)

These are hard-won lessons from production bugs. Save yourself the debugging.

| Gotcha | Details |
|--------|---------|
| PostgREST upsert | `?on_conflict=<column>` URL param required alongside `Prefer: resolution=merge-duplicates`. Without it: 409s. |
| Data source truth | `deepstack_positions` = current state. `deepstack_trades` = event log (stale). Never use trades for current positions. |
| Candlestick API path | `/series/{series_ticker}/markets/{ticker}/candlesticks` — NOT `/markets/{ticker}/candlesticks` |
| Mark-to-market | Balance = cash + (contracts x last_price), NOT portfolio_value (max payout) |
| Kelly fraction | Never set above 0.02 without empirical win rate data. 0.5 default is ruin at <50% win rate. |
| Exchange status | Check exchange open/closed before order placement. Orders fail silently on closed exchange. |
| Supabase overrides | Config-enabled strategies must be protected from stale dashboard state on bot restart. |

---

*Last updated: 2026-03-05*
*Private — id8Labs LLC*
