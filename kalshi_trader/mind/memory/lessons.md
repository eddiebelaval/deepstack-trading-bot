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

- calibration_edge enabled state contradicts standing rule on structural failure gating. Either retrain on holdout dataset or disable — no middle ground.
- calibration_edge structural failure (EV -5.9c, n=11) is non-recoverable without holdout dataset retraining — enabled state violates own standing rules.
- high_probability_bonds enabled with zero trade history — strategy validation is assumption-based, not data-backed.
- 16 open positions at $500 balance violates fractional Kelly principles. Position reconciliation needed to confirm inventory accuracy.
- Market regime detection pipeline returning 'unknown' — prevents proper strategy routing and regime-conditional risk management.
- calibration_edge structural failure (EV -5.9c, n=11) is non-recoverable without holdout retraining — enabled state violates own standing rules. Do not re-enable without validated holdout dataset.
- high_probability_bonds enabled with zero trade history — strategy performance is assumption-based until validation trades exist. Require n≥10 before meaningful capital allocation.
- Market regime 'unknown' blocks proper strategy routing — regime detection pipeline requires diagnostics. Unknown regime = conservative position sizing only.
- 15 open positions at $2K suggests fractional Kelly rounding may be deploying excess contracts. Verify position sizing math against current balance.
- Unknown market regime + 20 open positions = conservative position sizing mandatory until regime detection works.
- calibration_edge structural failure (EV -5.9c) and enabled state are mutually exclusive under standing rules — violation creates execution risk.
- high_probability_bonds enabled with zero validation trades — assumption-based strategies mask true edge discovery until n≥10 minimum.
- calibration_edge structural failure (EV -5.9c, n=11) and enabled state are mutually exclusive — standing rules create execution risk when violated.
- Unknown market regime + 23 open positions = position sizing vulnerability — conservative Kelly multipliers only until regime detection operational.
- Zero-history strategies (high_probability_bonds) enabled on assumption inflate false confidence in edge discovery — require minimum n≥10 before meaningful capital allocation.
- calibration_edge structural failure (EV -5.9c, n=11) is non-recoverable without holdout dataset retraining — enabled state violates standing rules.
- high_probability_bonds zero-history enablement masks true edge discovery — assumption-based strategies require n≥10 minimum before capital allocation.
- Unknown regime + high position count = position sizing vulnerability — conservative Kelly multipliers mandatory until regime detection operational.
- Unknown market regime + high position count = execution risk. Conservative Kelly multipliers mandatory until regime detection operational.
- calibration_edge structural failure (EV -46.9c, n=7) and enabled state are mutually exclusive under standing rules — creates execution compliance violation.
- Zero-history strategies (high_probability_bonds, tv_signals) enabled on assumption inflate false confidence. Require n≥10 minimum before meaningful capital allocation.
- calibration_edge structural failure (EV -46.9c) and enabled state are mutually exclusive — standing rules require disable or retrain before deployment.
- Unknown market regime blocks proper strategy routing and Kelly calculation — regime detection pipeline is critical infrastructure, not optional.
- 24 positions at $2K with unknown regime forces conservative position sizing — edge discovery is masked until regime clarity returns.
- mean_reversion showing early negative EV signal — small sample (n=3) requires validation, but trend is worth watching through next 5 trades.
