# SPEC.md -- Living Specification
## DeepStack

> Last reconciled: 2026-03-12 | Build stage: Phase 14 (Governance + Self-Awareness)
> Drift status: CURRENT
> VISION alignment: 70% (8 of 11 pillars realized, graduation auto-promotes)

---

## Identity

DeepStack is an autonomous multi-asset trading bot that synthesizes prediction market intelligence with traditional capital markets data. It trades Kalshi prediction markets (primary), IBKR stocks/ETFs/futures/options (expanding), and uses AI-driven governance to regulate its own behavior. The bot runs 24/7 via macOS launchd, reports through a live dashboard and Telegram, and learns from every trade via Bayesian posteriors and AI analysis.

## Capabilities

What this system can do TODAY.

### Trading Engine
- **Core Loop:** 60-second polling cycle. Update state, manage positions, scan opportunities, execute trades.
- **LIVE Trading (Kalshi):** Real money trades on `api.elections.kalshi.com` since 2026-03-11. Balance: $159.64. Kelly max position: ~$10 (6.3%). Daily loss limit: $5.
- **Paper Trading (IBKR):** Stocks, futures, options still in paper mode. Each sector graduates independently.
- **Multi-Asset Routing:** Positions route to correct exchange by asset_class (prediction_market -> Kalshi, stock/future/option -> IBKR).
- **Graceful Degradation:** asyncio.wait_for timeouts (10-15s) on all IBKR calls. When IBKR is disconnected, Kalshi strategies run unimpeded. Cycles complete in ~2 minutes regardless.

### Strategy Arsenal (19 strategies, 6 active)

| Strategy | Platform | Status | Win Rate | Notes |
|----------|----------|--------|----------|-------|
| calibration_edge | Kalshi | **LIVE** | 87% (145 trades) | Favorite-longshot bias. Best performer. Graduated 2026-03-11. |
| high_probability_bonds | Kalshi | ACTIVE | -- | Near-certainty contracts 93-98c. |
| stock_momentum | IBKR | ACTIVE (blocked) | -- | TradingView-validated equity momentum. Needs IBKR. |
| crisis_alpha | IBKR | ACTIVE (blocked) | -- | Inverse ETFs, volatility, safe havens, geopolitical. Needs IBKR. |
| options_income | IBKR | ACTIVE (blocked) | -- | Sold puts for income. Needs IBKR. |
| options_directional | IBKR | ACTIVE (blocked) | -- | Bought puts/calls directional. Needs IBKR. |
| futures_trend | IBKR | ACTIVE (blocked) | -- | Micro futures trend-following. Needs IBKR. |
| mean_reversion | Kalshi | DISABLED | 47.5% | Auto-disabled: critical health, negative EV. |
| momentum | Kalshi | DISABLED | -- | Governance disabled in low_vol_calm regime. |
| 10 others | Various | DISABLED | -- | settlement_betting, weather, news, arbitrage, etc. |

### Forward Signal Bridge
- **Signal Taxonomy:** RATE_SHIFT (KXFED), INFLATION (KXCPI), GROWTH (KXGDP), RISK_APPETITE (KXBTC/KXETH), GEOPOLITICAL (future).
- **Detection:** Price velocity analysis over rolling window. Needs 3+ data points per series. Threshold: 2-4 cents/cycle depending on signal type.
- **Regime Bias:** Detected signals boost or dampen stock regime confidence in GovernanceEngine. Confirming signals boost by 30%, conflicting signals dampen by 15%.
- **Status:** Ingesting data every cycle. No signals triggered yet (markets calm, below threshold).

### Governance Engine
- **Mode:** Autonomous (actuating, not advisory).
- **Regime Detection:** 5 regimes -- trending_up, trending_down, mean_reverting, high_vol_choppy, low_vol_calm.
- **Dual Regime:** Kalshi PM regime + IBKR stock regime (lookback=10 cycles, min_confidence=0.5).
- **Lexicon Signal Generator:** Maps regime to strategy recommendations via investor archetype consensus (Buffett, Icahn, Dalio, Burry, etc.).
- **Actuators:** Enable/disable strategies via strategy_manager. Log decisions with confidence and reasoning.
- **Short-Window Bleed Detection:** Per-strategy rolling 7-trade EV check. Fires `bleed_alert` governance decision before slope-based BleedDetector catches it.
- **Governance Priors:** All IBKR strategies have explicit regime fitness priors (crisis_alpha, options_directional added 2026-03-12).

### Risk Management
- **Kelly Sizing:** Dynamic per-strategy from realized win rate. Capped at 0.05.
- **Circuit Breakers:** Auto-disable after 5 consecutive losses, 10% drawdown, or <40% win rate over 20 trades.
- **Portfolio Halt:** Hard stop at min_balance_floor or max_portfolio_drawdown_pct.
- **Emotional Firewall:** Revenge trade detection, overtrading check, streak check (disabled in paper mode for data collection).
- **Adaptive Thresholds:** TP/SL adjust from performance tracker data. Refreshed every 100 cycles.

### Intelligence Layer
- **Trade Analyzer:** Claude Sonnet analysis of journal data every 30 minutes. Generates parameter_flags for strategy adaptation.
- **Captain's Log:** AI narration of bot state. Streams to dashboard COMMS panel and Supabase.
- **Heartbeat:** Deterministic health checks + periodic AI heartbeat. Arsenal refresh. Per-sector graduation evaluation with HTML report generation on pass.
- **Telegram Notifications:** 7 hooks — trade opened/closed, settlement, strategy auto-disable, inaction critical, daily summary, IBKR connection.

### Observability
- **Dashboard v3:** Live at milo.deepstack.trade (Vercel, deepstack-control project). Multi-page architecture:
  - `/` — Command Center: hero balance bar, strategy cards with health dots, AnalyticsPanel (6 chart views)
  - `/ops` — Operations: strategy toggles with enable/disable, Captain's Log feed, equity curve, risk meters
  - `/intel` — Intelligence: regime history table, governance decisions, forward signal bridge status, WeatherMap radar
  - `/graduation` — Graduation Gates: per-asset-class gate progress, fitness heatmap, gate check status
  - `/research` — TradingView indicator leaderboard with composite scoring
- **WeatherMap:** NOAA-style canvas radar visualization of market regime. D3 color interpolation, animated scan lines, 4-quadrant layout.
- **AnalyticsPanel:** 6 switchable views — daily P&L bars, cumulative equity line, drawdown chart, win rate trend with dual Y-axis, regime breakdown area chart, fitness heatmap grid.
- **API Security:** All PostgREST filters use `encodeURIComponent()`. Whitelist validation on sort columns, order direction. NaN guards on all numeric params. Strict ISO date regex validation.
- **Telegram Bridge:** Two-way communication. Bot sends alerts. User sends natural language commands. Memory across sessions.
- **Health Monitor:** Detects zombie states, opportunity drought, API connectivity, WAL size, log growth.
- **Logging:** Rotating log files (10MB rotation). Bot runs via launchd (com.id8labs.deepstack-bot).

### Crisis Trading (Built, Untested)
- **Inverse ETFs:** SQQQ (3x inverse Nasdaq), SDOW (3x inverse Dow), SH (inverse S&P), UVXY (volatility).
- **Safe Havens:** GLD (gold), TLT (long-term treasury bonds).
- **Geopolitical Plays:** USO (oil), XLE (energy sector), LMT/RTX/NOC (defense stocks).
- **Regime Gating:** trending_down = full crisis mode, high_vol_choppy = volatility + safe haven only, trending_up = geopolitical only.
- **Leverage Adjustment:** Stop-loss divided by leverage factor for leveraged products.

### Options (Built, Untested)
- **options_income:** Sell puts on stocks with high IV rank. Collect premium. Buy-back at target profit or stop loss.
- **options_directional:** Buy puts when regime=trending_down, calls when trending_up. ATM to 20% OTM, 14-45 DTE. TP at 50% gain, SL at 40% loss.

## Architecture Contract

| Layer | Technology | Notes |
|-------|-----------|-------|
| Runtime | Python 3.14, asyncio | Single-process, multi-task via asyncio.create_task |
| Kalshi API | httpx + RSA-PSS | Asymmetric key auth per request |
| IBKR API | ib_async | Single connection, sequential fetches |
| Database (local) | SQLite | Trade journal, arena results, consciousness |
| Database (cloud) | Supabase (scfdoayhmcruieppwawg, Oregon) | Dashboard state, positions, strategies |
| AI | Claude Sonnet 4.5 | Trade analyzer, Captain's Log, AI heartbeat |
| Dashboard | Next.js 14 + Supabase Realtime | Vercel deployment at milo.deepstack.trade |
| Process Manager | macOS launchd | com.id8labs.deepstack-bot |
| Notifications | Telegram Bot API | Chat bridge with memory |
| Backtesting | TradingView + deepstack-tradingview | 147 indicators, FastAPI server on port 8100 |

## Configuration

| Parameter | Value | Notes |
|-----------|-------|-------|
| poll_interval_seconds | 60 | Main cycle interval |
| max_position_size | $10 (real) / $125 (paper) | Paper scaled 12.5x from real balance |
| daily_loss_limit | $5 (real) / $62.64 (paper) | Hard stop per day |
| governance.lookback_periods | 10 | Cycles for regime detection (was 20) |
| governance.min_confidence | 0.5 | Act faster on regime shifts (was 0.6) |
| forward_signal_bridge.lookback_cycles | 10 | Price history window |
| forward_signal_bridge.signal_decay_cycles | 5 | Signal age-out |

## IBKR Watchlist (20 Tickers)

**Tradeable:** SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, SQQQ, SDOW, SH, UVXY, GLD, TLT, USO, XLE, LMT, RTX, NOC

**Regime Indicators Only:** DIA, IEF

## Graduation Gates

Hybrid graduation: 65% backtest confidence (arena scores) + 35% paper trading readiness. Each sector evaluated independently per heartbeat cycle. On graduation: generates HTML report to `~/Development/artifacts/deepstack/`, auto-promotes all strategies in the sector from paper to live (runtime flip + config.yaml persistence), and sends "AUTO-PROMOTED to LIVE" Telegram notification. No manual intervention required for paper-to-live transition.

| Asset Class | Required Trades | Required Win Rate | Hybrid Blend | Status |
|-------------|----------------|-------------------|-------------|--------|
| Kalshi (prediction_market) | 50 | 45% | Backtest: 17 strategies scored | **GRADUATED 2026-03-11.** 145 trades, 87% WR, 17.5% DD. LIVE. |
| Stocks | 30 | 50% | Backtest: scored | 0 paper trades. Needs IBKR market hours. |
| Futures | 20 | 45% | Backtest: scored | 0 paper trades. Needs IBKR market hours. |
| Options | 15 | 60% | Backtest: scored | 0 paper trades. Needs IBKR market hours. |

## File Map

```
kalshi-trading/
├── kalshi_trader/
│   ├── main.py                  # Core loop (~2900 lines)
│   ├── strategy_manager.py      # Multi-strategy orchestrator
│   ├── market_governor.py       # Autonomous governance + regime detection
│   ├── forward_signal_bridge.py # NEW: Cross-market intelligence (PM -> stock bias)
│   ├── captains_log.py          # AI narration
│   ├── trade_analyzer.py        # Claude analysis
│   ├── health_monitor.py        # Zombie detection
│   ├── graduation_gate.py       # Per-asset-class graduation evaluation
│   ├── graduation_report.py     # HTML report generator on graduation
│   ├── consciousness.py         # CaF self-awareness
│   ├── telegram_bridge.py       # Two-way Telegram
│   ├── dashboard_sync.py        # Supabase real-time sync
│   ├── kalshi_client.py         # RSA-authenticated API
│   └── journal.py               # Trade journal (SQLite)
├── strategies/
│   ├── base.py                  # Abstract Strategy + Kelly
│   ├── calibration_edge.py      # Favorite-longshot bias (BEST)
│   ├── stock_momentum.py        # IBKR equity momentum
│   ├── crisis_alpha.py          # NEW: Inverse ETFs, volatility, safe havens
│   ├── options_income.py        # Sold puts
│   ├── options_directional.py   # NEW: Bought puts/calls
│   ├── futures_trend.py         # Micro futures
│   └── ... (12 more)
├── markets/
│   ├── kalshi.py                # Kalshi API adapter
│   ├── polymarket.py            # Polymarket (read-only)
│   └── ibkr.py                  # Interactive Brokers adapter
├── arena/                       # Walk-forward tournament engine
├── config.yaml                  # Runtime configuration
├── BUILDING.md                  # Build journal (this file's sibling)
├── VISION.md                    # North star
└── SPEC.md                      # This file
```

---

*Last reconciled: 2026-03-12*
*Private -- id8Labs LLC*
