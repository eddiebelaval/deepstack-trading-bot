# BUILDING.md — DeepStack Trading Bot

This document tells the build story of DeepStack, an autonomous multi-asset trading bot. It evolved from a two-strategy prediction market weekend project into a wealth generation engine spanning Kalshi, IBKR stocks/ETFs/futures/options, with forward-looking intelligence from prediction markets, self-governing regime detection, and graceful degradation across exchanges.

**100+ commits. 13 active build days. Feb 7 — Mar 10, 2026.**

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

## Phase 10: Wealth Generation Engine (Mar 10)

**"A war is breaking out in Iran. This is how we make money."** Eddie's mandate: full-stack trading capability across all asset classes, forward-looking intelligence, and autonomous self-regulation. Close the loop.

### What Was Built

**Crisis Alpha Strategy** (`strategies/crisis_alpha.py`) -- NEW
- Buys inverse ETFs (SQQQ, SDOW, SH), volatility (UVXY), safe havens (GLD, TLT), and geopolitical plays (USO, XLE, LMT, RTX, NOC) during market stress
- Three tiers: conservative, aggressive, geopolitical. Regime-gated entry.
- Tighter stops for leveraged products (divided by leverage factor)
- `side="buy"` always -- inverse ETFs = short exposure via long position (no margin, no borrow, defined risk)

**Options Directional Strategy** (`strategies/options_directional.py`) -- NEW
- Buys puts when regime=trending_down, calls when trending_up
- ATM to 20% OTM, 14-45 DTE. TP at 50% gain, SL at 40% loss.
- Complements options_income (sold puts) -- now the bot can profit from moves in both directions

**Forward Signal Bridge** (`kalshi_trader/forward_signal_bridge.py`) -- NEW
- Prediction markets as leading indicators for stock regime detection
- Signal taxonomy: RATE_SHIFT (KXFED), INFLATION (KXCPI), GROWTH (KXGDP), RISK_APPETITE (KXBTC/KXETH)
- Price velocity detection over rolling window with short-term acceleration
- Regime bias injection: confirming signals boost stock regime confidence +30%, conflicting signals dampen -15%
- Wired into GovernanceEngine and Captain's Log

**IBKR Position Management Fix**
- Root cause: `_manage_positions()` routed ALL positions through Kalshi API. QQQ/SPY hit 404 errors.
- Fix: Route by `asset_class` -- IBKR positions to `_ibkr_market.get_market()`, Kalshi to Kalshi API.
- IBKR positions skip Kalshi-specific settlement logic (status checks, result handling)
- Journal reload infers asset_class from strategy name for position continuity across restarts

**IBKR Timeout Guards** -- the session's critical discovery
- IBKR TWS lost connectivity (Error 1100). All `await` calls to IBKR hung indefinitely.
- This blocked the ENTIRE trading cycle -- including Kalshi-only strategies. Bot appeared alive but never completed a cycle.
- Fix: `asyncio.wait_for()` timeouts on all 7 IBKR call sites:
  - Strategy manager scans (15s per strategy, 4 IBKR strategies)
  - Regime feed watchlist + indicators (15s each)
  - Dashboard holdings + balance push (10s)
  - Position management market data fetch (10s)
- Result: Cycles complete in ~2 minutes regardless of IBKR state. Kalshi strategies run unimpeded.

**Configuration Changes**
- IBKR watchlist expanded: 9 -> 20 tickers (added SQQQ, SDOW, SH, UVXY, GLD, TLT, USO, XLE, LMT, RTX, NOC)
- Governance lookback: 20 -> 10 cycles (faster regime detection)
- Governance min_confidence: 0.6 -> 0.5 (act faster on regime shifts)
- crisis_alpha and options_directional added to strategy config

**Triad Documents**
- Created VISION.md (north star) and SPEC.md (living specification)
- Updated BUILDING.md with Phase 10

### Architecture Decision: Timeout-First IBKR Integration
IBKR uses a single TCP connection (ib_async). When that connection drops, every `await` blocks forever because there's no built-in timeout. The fix -- wrapping every IBKR call in `asyncio.wait_for()` -- should have been there from day one. The principle: any external system call without a timeout is a potential cycle killer. Kalshi's httpx client has timeouts baked in; IBKR's ib_async does not. Trust no connection.

### Lessons
- **Inverse ETFs are the retail trader's short button.** Buying SQQQ = shorting Nasdaq without margin, borrow fees, or unlimited risk. The leverage is built into the product.
- **Prediction markets move first.** KXFED prices shift when rate expectations change. This happens before stocks reprice. The forward signal bridge captures this timing advantage.
- **Timeout starvation is silent death.** The bot looked healthy (httpx polling, Telegram responding) but hadn't completed a trading cycle in 15+ minutes. Without explicit timeout handling, one disconnected service can paralyze everything.
- **Graceful degradation beats hard dependencies.** The bot now runs Kalshi strategies 24/7 and automatically resumes IBKR strategies the moment TWS reconnects. No restart needed.

---

## Phase 11: Dashboard v3 + Security Audit (Mar 10)

**The dashboard was a single-page monolith with 34 orphaned components from v2.** This phase rebuilt it as a multi-page app and hardened every API route.

### What Was Built

**Dashboard v3 — Multi-Page Architecture**
- **4 dedicated pages** replacing the single-page layout:
  - `/` — Command Center: hero balance bar, strategy cards, analytics panel
  - `/ops` — Operations: strategy toggles, Captain's Log, equity curve, risk meters
  - `/intel` — Intelligence: regime history, governance decisions, forward signals
  - `/graduation` — Graduation Gates: per-asset-class gate progress with fitness heatmap
- **WeatherMap** (`components/WeatherMap.tsx`) — NOAA-style canvas radar visualization of market regime. D3 interpolateRgb color gradients, animated scan lines, quadrant labels.
- **AnalyticsPanel** (`components/AnalyticsPanel.tsx`) — 6 switchable chart views: daily P&L, cumulative, drawdown, win rate, regime breakdown, fitness heatmap. All recharts-based.
- **Terminal aesthetic** — green-on-black phosphor theme with custom CSS variables, glow effects, hierarchy system for visual depth.
- **Research page** (`/research`) — TradingView indicator leaderboard with composite scoring.

**Security Audit Remediation**
- **PostgREST filter injection** — 5 filter params in `lib/db-postgres.ts` were vulnerable to operator injection. Fixed with `encodeURIComponent()`.
- **Stricter ISO date regex** — validation for date params tightened to reject malformed timestamps.
- **API route hardening** — whitelist validation on sort columns, order direction, candlestick periods. NaN guards on all numeric params.
- **Backtest proxy** — removed silent localhost fallback, replaced with explicit 503 when `DS_TV_API_URL` not configured.

**Dead Code Cleanup**
- **34 orphaned components** deleted (v2 remnants: Sidebar, Header, StrategyRow, PnLChart, Toast, WinRateGauge, CaptainsLog, etc.)
- **3 unused hooks** deleted (useKeyboardShortcuts, useSessionTimeout, useSoundEffects)
- **3 dead API routes** deleted (/api/commands, /api/fills, /api/settlements)
- **~180 lines dead CSS** removed from globals.css (unused animations, dead classes)
- **Analytics API** migrated to `withDb()` pattern, added `VALID_VIEWS` set for early validation

**Bug Fixes**
- **D3 color format mismatch** — `hexToRGBA` assumed `#RRGGBB` but D3's `interpolateRgb` returns `rgb(R,G,B)`. Created `colorToRGBA` with regex detection of both formats.
- **Chart crashes on non-daily_pnl views** — YAxis ordering, null `.toFixed()` calls, SVG defs ordering in recharts.
- **formatStrategyName TypeError** — null coalescing guard `(name ?? 'UNKNOWN')`.
- **React key warnings** — duplicate keys in FitnessHeatmap fixed with index-composite patterns.

### Key Commits
```
084e20f feat(dashboard): v3 multi-page rewrite — graduation, ops, intel, chat
ca13a6d feat(engine): multi-asset graduation gates, IBKR bridge, new strategies
72435ca fix(security): audit remediation — filter injection, dead code cleanup
```

### Architecture Decisions
- **Multi-page over single-page**: The v2 dashboard crammed everything into one scrollable page. At 6+ panels, it was overwhelming and slow. Splitting by concern (command/ops/intel/graduation) keeps each page focused and fast.
- **Canvas radar over SVG chart**: WeatherMap uses raw canvas for the radar effect. SVG would've been cleaner for interactivity but canvas gives the authentic NOAA weather radar look that sells the terminal aesthetic.
- **Shared format utilities**: Centralized `REGIME_COLORS`, `formatGateValue`, `regimeColor` into `lib/format.ts` to eliminate duplication across 4+ components.

### Lessons
- **D3 color formats bite you**: `interpolateRgb` returns CSS `rgb()` strings, not hex. Any parser assuming hex will silently produce garbage colors. Always handle both formats.
- **Recharts component ordering matters**: `YAxis` with `yAxisId` must appear before any `Line`/`Bar` that references that ID. Silent crash otherwise.
- **Dead code compounds**: 34 orphaned components = 5,814 lines of deleted code. The v2→v3 rewrite left more dead code than live code. Regular audits prevent this accumulation.

---

## Phase 12: Graduation Reports + Notifications (Mar 10)

**"When we graduate a sector we need to generate a full HTML report."** Closing the loop on sector graduation — from detection to artifact.

### What Was Built

**Bot Crash Fix (P0)**
- `_notify()` method was accidentally placed inside `__init__`, splitting the constructor at line 186. Everything after — ~20 instance attributes including Kelly fractions, circuit breakers, inaction tracking — became part of `_notify()` body. Bot crashed immediately on startup with `AttributeError: '_config_disabled_strategies'`.
- Fix: moved `_notify()` to its own method after `__init__`.

**Graduation HTML Report Generator** (`kalshi_trader/graduation_report.py`) -- NEW
- Generates terminal-themed (green-on-black) HTML reports when any sector passes all gate checks
- Data from two sources: SQLite trade journal (paper metrics, daily P&L) + Supabase (backtest confidence from arena)
- Report contents: gate checks table, summary metrics, SVG equity curve sparkline, backtest strategy breakdown, regime performance (Kalshi), daily P&L table (last 14 days), blended readiness score
- Saved to `~/Development/artifacts/deepstack/graduation-{sector}-{timestamp}.html`

**Per-Sector Graduation in Heartbeat** -- UPGRADED
- Changed from Kalshi-only `evaluate()` to `evaluate_all()` — evaluates all 4 sectors (KALSHI, STOCKS, FUTURES, OPTIONS) independently
- Each sector can graduate independently, generating its own HTML report and Telegram notification
- `graduated_sectors` state list prevents duplicate notifications across bot restarts

**Telegram Trade Notifications** -- NEW (7 hooks)
- Trade opened: side, contracts, ticker, price, asset class, strategy
- Trade closed: ticker, exit type, P&L
- Market settlement: ticker, result, P&L
- Strategy auto-disable: name, reason
- Inaction critical: strategy, minutes idle
- Daily summary: trade count, P&L, per-strategy breakdown
- IBKR connection: success/failure with port

**Arena Backtest Persistence Fix**
- `gate='ALL'` was stored literally in Supabase instead of per-strategy gate resolution
- Root cause: `gate or _gate_for_strategy()` treats any truthy string as valid
- Fix: validate against `GATE_STRATEGIES.keys()` before using explicit gate
- Patched existing 17 rows via direct Supabase PATCH

### Key Commits
```
339ac99 feat(telegram): add trade notifications for all critical events
0985c4f feat(graduation): HTML report generation on sector graduation
```

### Lessons
- **Method placement in Python kills silently.** A `def` inside `__init__` doesn't raise a syntax error — it just ends `__init__` early and creates a new method. All subsequent attribute assignments become that method's body. The crash only surfaces when something tries to read the orphaned attributes.
- **Per-sector vs monolithic graduation:** The original heartbeat only checked Kalshi. But with 4 asset classes on different timelines (Kalshi has 38+ trades, IBKR has 0), each sector needs independent tracking. STOCKS could graduate months before OPTIONS.

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
├── strategies/               # 19 strategy plugins
│   ├── base.py              # Abstract Strategy + Kelly sizing
│   ├── calibration_edge.py  # Favorite-longshot bias (BEST: 92% WR)
│   ├── stock_momentum.py    # IBKR equity momentum
│   ├── crisis_alpha.py      # Inverse ETFs, volatility, safe havens
│   ├── options_income.py    # Sold puts
│   ├── options_directional.py # Bought puts/calls
│   ├── futures_trend.py     # Micro futures
│   ├── mean_reversion.py    # Buy near 50c
│   ├── momentum.py          # Trend-following
│   ├── settlement_betting.py # Near-expiry settlement capture
│   ├── high_probability_bonds.py
│   ├── weather_aggregation.py
│   ├── news_sentiment_fade.py
│   ├── combinatorial_arbitrage.py
│   ├── cross_platform_arbitrage.py
│   ├── correlated_event_arbitrage.py
│   ├── domain_specialization.py
│   ├── crypto_intraday.py
│   └── bear_macro.py
├── kalshi_trader/            # Core trading engine
│   ├── main.py              # Trading loop (~2900 lines)
│   ├── kalshi_client.py     # RSA-authenticated API
│   ├── strategy_manager.py  # Multi-strategy orchestrator (with IBKR timeouts)
│   ├── market_governor.py   # Autonomous governance (regime + forward signal bias)
│   ├── forward_signal_bridge.py # Cross-market intelligence (PM -> stock regime)
│   ├── captains_log.py      # AI narration
│   ├── trade_analyzer.py    # Claude-powered analysis
│   ├── health_monitor.py    # Zombie detection
│   ├── graduation_gate.py   # Per-asset-class graduation evaluation
│   ├── graduation_report.py # HTML report generator on graduation
│   ├── consciousness.py     # CaF self-awareness
│   ├── telegram_bridge.py   # Two-way Telegram
│   └── journal.py           # Trade journal (SQLite)
├── markets/                  # Exchange adapters
│   ├── kalshi.py            # Kalshi API
│   ├── polymarket.py        # Polymarket API (read-only)
│   └── ibkr.py              # Interactive Brokers (with LexiconOrderRouter)
├── dashboard/                # Next.js 14 control plane (v3 multi-page)
│   ├── app/
│   │   ├── page.tsx          # Command Center (hero bar, strategy cards, analytics)
│   │   ├── ops/page.tsx      # Operations (toggles, Captain's Log, equity curve)
│   │   ├── intel/page.tsx    # Intelligence (regime history, governance, signals)
│   │   ├── graduation/page.tsx # Graduation Gates (per-asset gate progress)
│   │   └── research/page.tsx # TradingView indicator leaderboard
│   ├── components/
│   │   ├── WeatherMap.tsx    # NOAA-style canvas radar (D3 color gradients)
│   │   ├── AnalyticsPanel.tsx # 6 chart views (recharts)
│   │   ├── Nav.tsx           # Terminal-style navigation
│   │   └── StratCard.tsx     # Strategy status cards
│   └── lib/
│       ├── db-postgres.ts    # PostgREST abstraction (security-hardened)
│       ├── format.ts         # Shared formatters (currency, time, regime colors)
│       └── types.ts          # TypeScript interfaces
├── tests/                    # 38+ tests
├── config.yaml              # Runtime configuration
├── trade_journal.db         # Local persistence (25MB)
└── arena_results.db         # Tournament results
```

## Strategy Count by Category

| Category | Count | Strategies |
|----------|-------|-----------|
| Prediction-native (active) | 2 | calibration_edge (92% WR), high_probability_bonds |
| Prediction-native (disabled) | 5 | mean_reversion, momentum, settlement_betting, weather_aggregation, news_sentiment_fade |
| Arbitrage | 3 | combinatorial, cross_platform, correlated_event |
| Stock/ETF (IBKR) | 2 | stock_momentum, crisis_alpha |
| Options (IBKR) | 2 | options_income, options_directional |
| Futures (IBKR) | 1 | futures_trend |
| Crypto | 1 | crypto_intraday |
| Framework | 2 | domain_specialization, bear_macro |
| Intelligence | 1 | tv_signals (TradingView) |

---

## Metrics

| Metric | Value |
|--------|-------|
| Total commits | 115+ |
| Active build days | 14 (Feb 7 — Mar 10, 2026) |
| PRs merged | 75 |
| Strategies | 19 (6 active, 13 disabled) |
| Tests | 38+ |
| Real balance | ~$159.64 (from $200 initial) |
| Paper balance | $2,000 |
| Best strategy | calibration_edge: 92% WR, 38 trades |
| Asset classes | 4 (prediction markets, stocks/ETFs, futures, options) |
| IBKR watchlist | 20 tickers |
| IBKR timeout sites | 7 (all protected) |
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
| IBKR timeouts | Every `await` on IBKR must use `asyncio.wait_for()`. ib_async has no built-in timeouts. One dropped connection kills the entire cycle. |
| IBKR single connection | ib_async uses one TCP socket. Run fetches sequentially, not with `asyncio.gather`. |
| Position routing | `asset_class` field determines API routing. IBKR positions must NOT go to Kalshi API. |

---

*Last updated: 2026-03-10*
*Private -- id8Labs LLC*
