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

- Capital constraint at $149.57 forces fractional Kelly to zero across non-Kalshi strategies. Graduation readiness is theoretical until balance supports minimum 1-contract positions.
- Idle strategies (enabled=true, n=0 trades, 48h+ inactivity) masquerade as optionality; implement auto-disable to reduce false confidence.
- Regime confidence <0.50 invalidates graduation gate progress; require regime stability >0.50 before trusting regime-gated scaling decisions.
- Capital floor ($150+) is hard constraint on fractional Kelly. Strategies requiring minimum 1-contract positions cannot execute until balance supports it.
- Balance below Phase 1 floor ($150). Fractional Kelly rounds to zero on most strategies. Graduation readiness is theoretical until balance recovers.
- Regime confidence 0.80 (high_vol_choppy) is your only reliable signal. Calibration_edge 86% win rate is regime-specific—test portability before scaling.
- 5 enabled strategies with zero trades (stock_momentum, correlated_event_arbitrage, etc.) add false confidence. Auto-disable after 48h inactivity per standing order.
- Mean_reversion EV=-12.3c (n=3) stays disabled. Re-enable only at EV>0 + n≥10 confirmed.
- Balance dropped below Phase 1 floor ($150). Fractional Kelly now rounds to zero on most strategies. Growth stalled until balance recovers to $150+.
- High_vol_choppy regime (0.80 confidence) is only reliable signal. All profitable strategies are regime-specific—portability untested.
- Calibration_edge dominates portfolio (157/159 total trades). Concentration risk masked by positive strategy performance. Diversification blocked by capital constraint and zero idle-strategy execution.
- Five enabled strategies with zero trades (correlated_event_arbitrage, high_probability_bonds, etc.) are dead weight. Auto-disable idle strategies after 48h per standing order.
- In choppy regimes, fewer positions with tighter management outperform high position counts
- In choppy markets, reduce position count to increase focus and manageability
- High volatility requires wider stops or smaller position sizes to avoid false breakout losses
- Choppy markets require tighter stops and smaller position sizes to avoid multiple small losses
- High volatility with chop suggests reduced directional bias; favor mean-reversion strategies
- In choppy markets, reduce position count or use tighter stops to avoid death-by-a-thousand-cuts losses
- Reduce position count in choppy markets to improve manageability
- Tighten stop losses during high volatility regimes
- Reduce position count during choppy regimes to improve manageability
- Tighten stops and reduce lot sizes when volatility spikes without clear direction
- Regime confidence <0.50 invalidates graduation gate progress. Low_vol_calm (0.30) is not a testable regime for strategy portability.
- Enabled strategies with zero trades for 48h+ are confidence illusions. Implement auto-disable to reduce false optionality.
- Fractional Kelly at sub-$150 balance forces all non-dominant strategies to zero contracts. Growth requires balance recovery to $150+ first.
