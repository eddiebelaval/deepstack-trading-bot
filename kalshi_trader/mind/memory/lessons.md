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

- Position inventory mismatch from prior heartbeat (21 contracts) has fully resolved — data integrity self-corrected or positions were legacy artifacts.
- calibration_edge (EV -5.9c, n=11) structural failure confirmed non-recoverable without holdout dataset retraining — permanently gate re-enablement.
- momentum (61% WR, 9.6c EV, n=2) remains sole re-enablement candidate but n=2 is statistically unreliable — requires 48+ validation trades to reach n≥50 confidence threshold.
- calibration_edge (EV -5.9c, n=11) structural failure confirmed — holdout dataset retraining mandatory gate before any re-enablement consideration.
- momentum (61% WR, 9.6c EV, n=2) sole re-enablement candidate — requires 48+ validation trades to reach statistical threshold (n≥50).
- Sub-$500 balance forces all strategies to zero contracts via fractional Kelly — idle state is only defensible position.
- Sub-$500 balance is a hard floor: fractional Kelly rounds all strategies to zero contracts. Idle is the only defensible state until capital reaches $500+.
- calibration_edge (EV -5.9c, n=11) is structurally miscalibrated — holdout dataset retraining is mandatory gating criterion before any re-enablement. Do not activate without model validation.
- momentum (61% WR, 9.6c EV, n=2) is sole re-enablement candidate but n=2 lacks statistical power — requires 48+ additional validation trades to reach n≥50 confidence threshold.
- Idle state persists: sub-$500 balance forces all strategies to zero contracts. No capital deployment until $500+ threshold reached.
- calibration_edge remains structurally miscalibrated (EV -5.9c, n=11) — holdout retraining mandatory before any re-enablement consideration.
- momentum (61% WR, 9.6c EV, n=2) is only viable candidate for future re-enablement but requires 48+ validation trades to reach n≥50 confidence.
- Capital threshold achieved ($500). Fractional Kelly rounding no longer forces zero contracts — strategies can now deploy with proper position sizing.
- calibration_edge enabled despite documented structural failure (EV -5.9c, n=11). Enabled state contradicts standing rule: 'holdout dataset retraining is mandatory gating criterion before any re-enablement.' Disable until model is retrained.
- high_probability_bonds lacks any trade history (0 trades, 0.0c EV). Strategy enabled on assumption only. Requires validation trades before meaningful capital allocation.
- Capital threshold $500 reached — fractional Kelly rounding no longer constrains position sizing. Strategies can now deploy with proper kelly multipliers.
- calibration_edge enabled state contradicts standing rule on structural failure gating. Either retrain on holdout dataset or disable — no middle ground.
- calibration_edge structural failure (EV -5.9c, n=11) is non-recoverable without holdout dataset retraining — enabled state violates own standing rules.
- high_probability_bonds enabled with zero trade history — strategy validation is assumption-based, not data-backed.
- 16 open positions at $500 balance violates fractional Kelly principles. Position reconciliation needed to confirm inventory accuracy.
- Market regime detection pipeline returning 'unknown' — prevents proper strategy routing and regime-conditional risk management.
- calibration_edge structural failure (EV -5.9c, n=11) is non-recoverable without holdout retraining — enabled state violates own standing rules. Do not re-enable without validated holdout dataset.
- high_probability_bonds enabled with zero trade history — strategy performance is assumption-based until validation trades exist. Require n≥10 before meaningful capital allocation.
- Market regime 'unknown' blocks proper strategy routing — regime detection pipeline requires diagnostics. Unknown regime = conservative position sizing only.
- 15 open positions at $2K suggests fractional Kelly rounding may be deploying excess contracts. Verify position sizing math against current balance.
