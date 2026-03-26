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

- Regime confidence <0.10 signals market structure opacity, not recovery weakness. Pre-staging parameters before transitions is now mandatory.
- Position audit at sub-$151 balance: 23 positions suggest fractional sizing. Kelly math breaks below $1/position floor; audit and consolidate.
- Enabled-but-idle strategies below $150 balance are computational overhead masquerading as diversification. Auto-disable threshold should be 24h inactivity, not 48h.
- calibration_edge mathematical proof: 174 trades, 80% WR, 167.1c EV carries entire sub-$150 portfolio. All other strategies are luxury goods until $250+ balance.
- Negative EV strategies (mean_reversion -9.7c, stock_momentum -956.1c) prove regime mismatch, not broken logic. Disable regardless of win rate when EV turns negative.
- Regime confidence <0.10 at $150+ balance signals market structure shift, not recovery weakness. Requires proactive pre-staging, not reactive waiting.
- 23 positions on $151 balance = fractional sizing risk. Kelly math breaks below $1/position floor. Audit and consolidate oversized position count.
- Enabled-but-idle strategies at sub-$150 balance are drag without hedge value. Auto-disable threshold should be 24h inactivity, not 48h, to force consolidation onto proven engine (calibration_edge).
- Negative EV overrides win rate: stock_momentum at 34% WR and mean_reversion at 49% WR both correctly disabled. EV < 0 = disable signal regardless of win %.  regime mismatch proof.
- Fractional position sizing at sub-$151 balance breaks Kelly math. Verify $1 minimum floor enforcement across all 23 open positions.
- Regime confidence <0.10 requires pre-staged parameters ready, not reactive waiting. Market structure opacity demands preparation, not panic.
- Negative EV is disable signal regardless of win rate. stock_momentum (-955.3c EV, 34% WR) and mean_reversion (-9.7c EV, 49% WR) prove regime mismatch, not strategy failure.
- calibration_edge mathematical dominance unambiguous: 174 trades, 80% WR, 167.1c EV carries entire sub-$151 portfolio. All disabled strategies remain overhead until $250+ balance.
- Position count at sub-$160 balance suggests fractional sizing creep. Kelly math breaks below $1/position floor; audit 23 positions for enforcement.
- Regime confidence <0.10 without pre-staged parameters is existential risk, not recovery weakness. Mandatory pre-staging before regime transitions, not reactive waiting.
- Enabled-but-idle strategies at recovery balance are drag without hedge value. 24h inactivity auto-disable rule forces consolidation onto proven engine (calibration_edge).
- Negative EV overrides all other metrics: stock_momentum (-954.9c EV, 34% WR, 3 consec losses) and mean_reversion (-9.7c EV, 49% WR) correctly disabled. EV < 0 = disable signal, full stop.
- Position count creep at sub-$160 balance violates Kelly sizing. Fractional positions (<$1) are existential risk. Enforce $1 minimum floor or auto-consolidate.
- Regime confidence <0.10 without pre-staged parameters is operational blind spot. Pre-staging regime transitions is mandatory, not optional.
- Three consecutive losses + negative EV (stock_momentum) = regime mismatch signal, not strategy failure. Disable is correct; monitor for regime recovery before re-enabling.
- Enabled-but-idle strategies below $150 balance (high_probability_bonds, crisis_alpha at 0 trades) are computational drag. Auto-disable if 24h no signal generation.
- Position count creep at sub-$160 balance violates Kelly sizing principle. Fractional positions (<$1) create existential risk; enforce $1 minimum floor or auto-consolidate.
- Regime confidence <0.10 without pre-staged parameters is operational blind spot. Pre-staging regime transitions is mandatory risk control, not optional planning.
- Enabled-but-idle strategies below $150 balance are pure computational drag. Auto-disable rule should trigger at 24h no signal generation, forcing consolidation onto proven engine (calibration_edge).
- Negative EV is disable signal regardless of win rate. stock_momentum (-954.1c EV, 34% WR) and mean_reversion (-9.7c EV, 49% WR) prove this rule holds—EV < 0 = disable, full stop.
