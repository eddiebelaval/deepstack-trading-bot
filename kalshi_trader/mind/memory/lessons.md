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

- calibration_edge structural failure (EV -46.9c) and enabled state are mutually exclusive — standing rules require disable or retrain before deployment.
- Unknown market regime blocks proper strategy routing and Kelly calculation — regime detection pipeline is critical infrastructure, not optional.
- 24 positions at $2K with unknown regime forces conservative position sizing — edge discovery is masked until regime clarity returns.
- mean_reversion showing early negative EV signal — small sample (n=3) requires validation, but trend is worth watching through next 5 trades.
- calibration_edge structural failure (EV -46.9c) and enabled state are mutually exclusive under standing rules — creates execution compliance violation.
- mean_reversion early negative trend (n=3, EV -14.3c) requires validation through n=10 before disabling, but trajectory is worth monitoring closely.
- calibration_edge structural failure (EV -46.9c, n=7) and enabled state are mutually exclusive — standing rules require disable or retrain before deployment.
- Unknown market regime + 24 open positions forces conservative position sizing — edge discovery is masked until regime clarity returns.
- Unknown market regime + 10 open positions forces conservative position sizing — edge discovery is masked until regime clarity returns.
- Zero-history strategies (tv_signals) enabled on assumption inflate false confidence — require n≥10 minimum before meaningful capital allocation.
- calibration_edge structural failure (EV -46.8c) and enabled=True are mutually exclusive — standing rules require disable or retrain before deployment.
- mean_reversion early negative EV (n=3, -14.3c) — small sample but trend warrants close monitoring through n=10 validation window.
- Unknown market regime forces conservative position sizing regardless of strategy signal strength — regime detection is critical infrastructure.
- calibration_edge negative EV + enabled state = execution compliance violation under standing rules.
- mean_reversion n=3 sample too small to disable, but -14.3c EV trajectory requires validation through n=10.
- Unknown regime forces conservative Kelly multipliers; regime detection is blocking full edge extraction.
- calibration_edge negative EV + enabled state = execution compliance violation — standing rules must override strategy output.
- mean_reversion early negative EV (n=3) requires n≥10 validation window before disable decision — small sample but trajectory matters.
- Unknown regime forces conservative Kelly regardless of signal strength — regime detection is blocking edge extraction, not optional.
- calibration_edge negative EV + enabled state = execution compliance violation under standing rules — disable until retrained on holdout data.
- mean_reversion negative EV (n=3) too small to disable but trajectory warrants validation through n=10 before strategy-level decision.
- Unknown regime forces conservative position sizing regardless of signal strength — regime detection infrastructure blocks full alpha extraction.
- calibration_edge structural failure (EV -46.8c) makes enabled=True a compliance violation — standing rules require disable or retrain.
- mean_reversion negative EV on small sample (n=3) signals early structural issue — validate through n=10 before disable decision.
- Unknown regime + 10 open positions forces conservative Kelly regardless of signal strength — regime detection infrastructure is blocking edge extraction.
