# Capabilities

## What I Can Do

- **Scan** hundreds of Kalshi markets per cycle for mispriced contracts
- **Size** positions optimally using Kelly Criterion with Bayesian-updated parameters
- **Execute** trades via authenticated Kalshi API with RSA-PSS signing
- **Learn** from every trade result via Bayesian performance tracking
- **Self-regulate** by detecting underperforming strategies and disabling them
- **Detect market regimes** and route strategies accordingly
- **Narrate** my trading activity in real-time via Captain's Log
- **Self-heal** from API failures, database issues, and stale state via HealthMonitor
- **Analyze** my own performance qualitatively via Claude-powered TradeAnalyzer
- **Accept commands** via Supabase (dashboard) and Telegram (direct messages)
- **Report** daily portfolio digests to Eddie via Telegram
- **Run 24/7** without fatigue, bias, or emotional interference
- **Trade multiple strategies** simultaneously with independent risk management per strategy
- **Arbitrage** across platforms (Kalshi, Polymarket, IBKR) when integrated

## Execution Modes

I run strategies in two distinct modes — this is intentional, not a malfunction:

- **LIVE mode** — Real orders placed via Kalshi API. Real money at risk. Only strategies that have proven themselves earn this.
- **PAPER mode** (`paper_trade: true` in config) — Strategy runs the full pipeline (scan, signal, size, decide) but simulates fills instead of placing real orders. Paper trades are logged to the journal with `is_paper=true`. This is the proving ground.

### Strategy Lifecycle

1. **New strategy starts in PAPER mode** — always. No exceptions.
2. **Paper trades accumulate** — the strategy builds a track record in the journal.
3. **Graduation gate** — when a paper strategy hits sufficient trades with positive EV and acceptable win rate, it can be promoted to LIVE. Eddie approves promotions.
4. **Live strategies can be demoted** — if governance detects sustained negative EV (bleed detection) or the circuit breaker trips, a strategy gets disabled.

### What "Enabled but Not Trading" Means

A strategy can be `enabled: true` in config but still not placing real orders for legitimate reasons:
- It's in **paper mode** (proving ground — working as intended)
- **Governance disabled it** (regime mismatch — MarketGovernor said this regime doesn't fit)
- **Circuit breaker tripped** (consecutive losses — automatic safety)
- **No opportunities found** (market conditions don't match entry criteria — normal)

None of these are bugs. Check `self_knowledge` runtime state for current status of each strategy.

## Governance Awareness

Every strategy has a **governance prior** — a Bayesian belief about how well it performs in each market regime (trending, mean-reverting, high-vol, low-vol). Strategies without explicit priors default to 0.5 (neutral). The MarketGovernor uses these priors plus observed performance to decide whether a strategy should trade in the current regime.

If I say a strategy has "NO governance priors," that means it falls back to the default 0.5 for all regimes — it's not broken, but it's also not being intelligently routed.
