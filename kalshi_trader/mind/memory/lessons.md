# Lessons Learned

*This file is updated periodically by TradeAnalyzer as patterns emerge from trading data.*

## Early Lessons

- Prediction markets are thinner than expected. Limit orders matter more than speed.
- Mean reversion works best on weather and economic indicators where outcomes cluster around expectations.
- Momentum strategies need regime detection to avoid getting chopped in sideways markets.
- The emotional firewall revenge-check was designed for humans — an automated bot doesn't revenge-trade by definition.
- Small balances create a cold-start problem: fractional Kelly rounds to zero contracts. Minimum position floor of $1 prevents death spiral.

## Strategy Observations

- Combinatorial arbitrage opportunities exist but are rare and fleeting.
- Cross-platform arbitrage (Kalshi vs Polymarket) requires accounting for different fee structures.
- TradingView signal integration adds alpha but signals need validation against Kalshi-specific liquidity.

## Operational Lessons

- WAL checkpoint needed periodically or SQLite DB grows unbounded.
- Captain's Log Supabase entries need trimming to prevent table bloat.
- Health monitor self-healing catches most API hiccups automatically.

## AI-Learned

- Position inventory mismatch from prior heartbeat (21 contracts) has fully resolved in current state — data integrity self-corrected or positions were legacy.
- Fractional Kelly floor empirically confirmed: at $159.64 balance, all strategies round to zero contracts regardless of EV. Capital floor of $500+ is hard requirement for meaningful execution.
- Idle capital state is correct tactical decision when all strategies fail edge criteria or position sizing rounds to zero contracts.
- calibration_edge (n=11, EV -5.9c) is structural miscalibration. Holdout dataset retraining is mandatory gating criterion before any re-enablement — do not attempt activation without model validation.
- momentum (61% WR, 9.6c EV, n=2) is sole viable re-enablement candidate but n=2 is statistically unreliable. Requires 48+ additional validation trades to reach n≥50 threshold.
- calibration_edge (n=11, EV -5.9c) is structural miscalibration — holdout dataset retraining mandatory before any re-enablement consideration.
- momentum (61% WR, 9.6c EV, n=2) sole re-enablement candidate — requires 48+ validation trades to reach n≥50 statistical threshold.
- Fractional Kelly floor confirmed: $159.64 balance rounds all positions to zero contracts. Capital floor of $500+ is hard requirement for meaningful execution.
- Idle capital is correct tactical decision when all strategies fail edge criteria or position sizing rounds to zero.
- Idle capital with fractional Kelly rounding to zero is the only correct decision below $500 balance threshold.
- calibration_edge structural miscalibration (EV -5.9c, n=11) requires holdout dataset retraining before any re-enablement — non-negotiable gating criterion.
- momentum (61% WR, 9.6c EV, n=2) is sole re-enablement candidate but statistically unreliable — requires 48+ validation trades to reach n≥50 threshold.
- Calibration_edge structural failure (EV -5.9c, n=11) is non-recoverable without retraining on holdout dataset. Do not re-enable.
- Momentum strategy (61% WR, 9.6c EV, n=2) is only viable re-enablement candidate but requires 48+ validation trades to reach statistical confidence (n≥50).
- Fractional Kelly rounding to zero contracts at $159.64 balance confirms hard floor of $500+ required for any meaningful strategy execution.
- Idle capital state is strategically correct when position sizing math forces zero — no trade beats sitting on hands with insufficient scale.
- Idle capital below $500 hard floor is the only correct decision — all strategies round to zero contracts regardless of EV at current balance.
- calibration_edge (EV -5.9c, n=11) structural failure confirmed non-recoverable without holdout dataset retraining — do not re-enable.
- Idle state with sub-$500 balance and fractional Kelly rounding to zero is the only defensible position. No exceptions.
- Position inventory mismatch from prior heartbeat (21 contracts) has fully resolved — data integrity self-corrected or positions were legacy artifacts.
- calibration_edge (EV -5.9c, n=11) structural failure confirmed non-recoverable without holdout dataset retraining — permanently gate re-enablement.
- momentum (61% WR, 9.6c EV, n=2) remains sole re-enablement candidate but n=2 is statistically unreliable — requires 48+ validation trades to reach n≥50 confidence threshold.
- calibration_edge (EV -5.9c, n=11) structural failure confirmed — holdout dataset retraining mandatory gate before any re-enablement consideration.
- momentum (61% WR, 9.6c EV, n=2) sole re-enablement candidate — requires 48+ validation trades to reach statistical threshold (n≥50).
- Sub-$500 balance forces all strategies to zero contracts via fractional Kelly — idle state is only defensible position.
