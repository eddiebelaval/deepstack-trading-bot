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

- Negative EV strategies (mean_reversion -14.6c, calibration_edge -5.9c) are losing money by definition. Disabling them was correct; re-enabling without fixes compounds losses.
- Small sample sizes (3-11 trades per strategy) mean confidence intervals are wide. Win rate alone is meaningless without EV floor validation.
- Bot sitting idle with $159.64 is capital inefficiency. Either confidence in next trade is zero (correct) or decision rules for strategy re-enablement are missing (needs fixing).
- Negative EV strategies must be disabled. Period. Win rate is a false signal when expected value is red.
- Idle capital at low balance means decision rules for strategy re-enablement are missing. Need explicit criteria to exit idle state.
- Small sample sizes (3-11 trades) create false confidence. Require minimum 50 trade sample before evaluating strategy health.
- Idle capital at low balance signals missing re-enablement criteria. Define explicit thresholds (e.g., EV > 5c, win_rate > 55% over 50+ trades) before re-enabling any strategy.
- calibration_edge shows -5.9c EV over 11 trades — negative expected value by definition. Keep disabled until model recalibration produces positive EV on test data.
- mean_reversion shows -14.6c EV over 3 trades. Too small a sample to conclude, but negative EV means no re-enable until back-tested against larger dataset.
- momentum (61% win rate, 9.6c EV, 2 trades) and combinatorial_arbitrage (80% win rate, 1.2c EV, 0 trades) are candidates for re-enablement once sample size and EV confidence thresholds are met.
- All active strategies currently disabled due to negative EV or insufficient sample size. Re-enablement requires explicit criteria: minimum 50-trade sample, EV > 0, win rate > 40%.
- Idle capital at $159.64 indicates decision paralysis. Either market conditions offer no edge (defensible) or strategy selection process needs codification to exit stall.
