# Dynamic Kelly Sizing Based on Confidence

**Priority:** P1 — Important, but toggles + breakers come first
**Owner:** Claude
**Status:** Pending

---

## What?

Kelly fraction adjusts dynamically based on:

1. **Strategy win rate history** (rolling last 30 trades)
2. **Recent P&L volatility** — high variance = lower sizing
3. **Signal confidence score** (when available from strategy)

Sizing guardrails:
- **Range:** 0.1x to 0.3x Kelly
- **Default:** 0.25x if no data yet (conservative start)
- **Floor:** Never bet more than Kelly suggests, even on hot streaks
- **Zero threshold:** If rolling win rate < 20%, Kelly goes to minimum (0.01x) — essentially learning-only mode

### Confidence Decay Factor (Small Sample Protection)

Strategies with < 30 trades don't have enough data for confident Kelly sizing. Scale down by sample size:

```
effective_kelly = base_kelly * sqrt(num_trades / 30)
```

| Trades | Decay Factor | Effect on 0.25x Kelly |
|--------|-------------|----------------------|
| 5      | 0.41        | 0.10x (near floor)   |
| 10     | 0.58        | 0.14x               |
| 20     | 0.82        | 0.20x               |
| 30+    | 1.00        | 0.25x (full weight)  |

**Why?** Market making had only ~10 trades at 30% win rate. That's not enough data to be confident it's broken — but it's also not enough to bet aggressively. The sqrt decay smoothly ramps up confidence as sample size grows, preventing premature judgments on new strategies while still respecting the data we have.

### Win Rate Scaling

Once confidence is established (30+ trades):
- Win rate > 60% → scale to 0.30x (aggressive, earned it)
- Win rate 40-60% → scale proportionally within 0.15x-0.30x
- Win rate < 40% → circuit breaker territory (P0 handles this)

## Why?

Right now Kelly is static at 0.5x regardless of how the strategy is performing. A struggling strategy (17.4% win rate) should be sizing down to near-zero, not betting the same as a winning strategy. The static 0.5 was way too aggressive — at 17% win rate, true Kelly is actually *negative* (meaning: don't bet at all). The system already had `PerformanceTracker.get_blended_stats()` but it wasn't connected to actual trade sizing until PR #34. Now we need it to respond faster and with tighter bounds.

## Done When?

- [ ] Kelly fraction recalculates after every trade closure
- [ ] Each strategy has its own independent Kelly fraction
- [ ] Rolling 30-trade window (not all-time, which dilutes recent signal)
- [ ] Dashboard shows current Kelly fraction per strategy
- [ ] Backtest confirms sizing reduces on losing streaks
