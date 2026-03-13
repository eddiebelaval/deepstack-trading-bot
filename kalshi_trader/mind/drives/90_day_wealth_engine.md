# 90-Day Wealth Engine Plan

> Created: 2026-03-13
> Status: ACTIVE — Phase 1
> Starting Balance: $159.64
> First Oak Tree Report: Sunday, March 16, 2026

---

## Mission

Turn $159.64 into the seed of generational wealth. Not through heroics — through disciplined, compounding edge exploitation. Every decision serves the phase we're in (SEED). Every trade earns or teaches. No trade does neither.

---

## Phase 1: Diagnostics (Days 1-14 | Mar 13-27)

**Objective:** Understand what's working, kill what isn't, fix blind spots.

### Actions
1. **Audit calibration_edge performance** — Break down win rate by market series (KXBTC, KXETH, KXFED, KXCPI, KXGDP). Identify which series contribute edge vs noise.
2. **Disable idle strategies** — Any strategy with 0 trades and 48h+ enabled is cognitive overhead. Auto-disable per standing order in lessons.md.
3. **Fix regime detection confidence** — Low_vol_calm confidence has been oscillating between 0.10-0.57. Regime gate (2/2 required for graduation scaling) is the real blocker.
4. **Tighten risk parameters** — Max position $6 (was $10). Circuit breaker at 3 consecutive losses (already set). Daily loss limit $5 (already set).
5. **Baseline metrics** — Record: balance, daily P&L, win rate, regime distribution, active positions.

### Success Criteria
- Balance: $150-180 (preserve capital, don't bleed)
- Win rate: maintain 80%+ on calibration_edge
- Regime: achieve confidence >0.50 in at least 1 regime consistently
- Idle strategies: all 0-trade strategies disabled

### Decision Rules
- If balance drops below $130: HALT all trading for 24h. Review.
- If win rate drops below 70%: reduce max position to $3.
- If 3 consecutive losses in same series: disable that series for 48h.

---

## Phase 2: Optimization (Days 15-45 | Mar 28 - Apr 27)

**Objective:** Refine the edge. Expand regime coverage. Grow to $300-500.

### Actions
1. **Regime diversification** — Trade through at least 2 validated regimes (current blocker: 0/2).
2. **Parameter tuning** — Use AI analysis recommendations to adjust entry/exit thresholds. Bounded by +/-50% from baseline per apply_parameter_flags().
3. **Series expansion** — If a new Kalshi series shows liquidity + edge in backtests, add it to calibration_edge markets.
4. **Position scaling** — As balance grows past $250, increase max position from $6 to $10. Past $400, increase to $15.
5. **IBKR monitoring** — Track paper trades on stock_momentum, futures_trend, options_income. No live graduation yet.

### Success Criteria
- Balance: $300-500
- Regimes validated: 2+ (graduation gate unblocked)
- Positive P&L in 3 of 4 weeks
- No single drawdown exceeding 15%

### Decision Rules
- If balance hits $300: increase max position to $10, keep Kelly at 0.02.
- If balance hits $500: SEED phase complete, CapitalAllocator auto-transitions to GROWTH.
- If drawdown exceeds 15% from peak: cut position sizes by 50%, reassess.

---

## Phase 3: Compounding (Days 46-90 | Apr 28 - Jun 11)

**Objective:** Compound gains. Begin GROWTH phase diversification if balance supports it.

### Actions
1. **GROWTH phase activation** — If balance exceeds $500, CapitalAllocator shifts allocations: diversify beyond calibration_edge alone.
2. **IBKR graduation assessment** — If any IBKR sector passes graduation gates (30+ trades, 50% WR, <10% DD), auto-promote to live.
3. **Strategy health monitoring** — Weekly analysis of per-strategy Kelly fractions. Prune strategies that have proven negative EV over 50+ trades.
4. **Reserve discipline** — Maintain 70% reserve in SEED, 60% in early GROWTH.
5. **First Oak Tree Report retrospective** — Compare actual trajectory to this plan. Adjust for Phase 4 (beyond 90 days).

### Success Criteria
- Balance: $800-1500
- At least 2 strategies contributing positive P&L
- IBKR paper trades: 30+ across all sectors
- Max drawdown across full 90 days: <20%

### Decision Rules
- If balance hits $1000: celebrate quietly, increase daily loss limit to $10.
- If balance drops below $300 after reaching $500: re-enter SEED mode, cut all position sizes.
- If IBKR paper results are strong: begin graduated live allocation per heartbeat auto-promote logic.

---

## Risk Guardrails (Always Active)

| Guardrail | Threshold | Action |
|-----------|-----------|--------|
| Daily loss limit | $5 | Halt all trading for remainder of day |
| Min balance floor | $50 | Halt ALL trading until manual review |
| Max drawdown | 20% from session start | Halt ALL trading |
| Consecutive losses | 3 per strategy | Circuit breaker trips, strategy disabled |
| Portfolio heat | >25% of balance exposed | No new positions until heat reduces |
| Kelly fraction | 0.02 (fractional) | Never exceed. $1 minimum floor. |

---

## Reporting

### Oak Tree Report (Weekly — Sundays)
1. Balance vs target for current phase
2. Per-strategy P&L breakdown
3. Lessons learned (from lessons.md)
4. Regime detection status
5. Strategies enabled/disabled and why
6. Next week's focus

### Telegram Alerts (Real-time)
- Every trade placed (entry + reasoning)
- Every trade closed (exit + P&L)
- Circuit breaker trips
- Daily P&L threshold breaches
- Oak Tree Report summary

---

## What To Do When Things Go Wrong

| Scenario | Response |
|----------|----------|
| 3 consecutive losses | Circuit breaker auto-disables strategy. Review in next heartbeat. |
| Balance drops 10%+ in a day | Stop trading. Message Eddie. Don't resume until manual review. |
| Regime detection stuck | Fall back to "unknown" regime. Conservative allocation. |
| API errors / connectivity | Graceful degradation. Kalshi strategies continue if IBKR fails. |
| Strategy produces 50+ trades with negative EV | Permanently disable. Document in lessons.md. |
| External crisis (Black Swan) | Check crisis_alpha readiness. If not graduated, observe only. |

---

*This plan is Dae's compass. Read it. Execute it. Report against it. Update it when reality teaches us something new.*
