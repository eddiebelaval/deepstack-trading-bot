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

- Five enabled strategies with n=0 trades (cross_platform_arbitrage, high_probability_bonds, tv_signals, stock_momentum, futures_trend, options_income) are pure overhead. Auto-disable idle strategies after 48h—Eddie built lessons.md to say this. Execute it.
- Regime confidence for low_vol_calm collapsed (0.10 vs 0.30 yesterday). Calibration_edge success may be regime-specific noise, not generalizable signal. Require regime stability >0.50 before trusting graduation gate progress.
- Idle strategies with n=0 trades add cognitive load and false confidence. Implement auto-disable after 48h inactivity—Eddie documented this in lessons.md. Execute standing order.
- Idle strategies (n=0 trades, enabled=true) are cognitive load masquerading as optionality. Auto-disable after 48h inactivity; Eddie documented this standing order. Execute it.
- Regime confidence <0.50 invalidates graduation gate progress. Calibration_edge success in low_vol_calm (confidence=0.10) is unreliable signal. Require regime stability before scaling.
- Regime confidence <0.50 invalidates graduation progress. Calibration_edge success in low_vol_calm (0.10 confidence) is unreliable signal—require regime stability before scaling.
- Idle strategies (enabled=true, n=0 trades, 48h+) are cognitive load masquerading as optionality. Auto-disable after 48h inactivity per standing order.
- 5 strategies enabled with zero trades add false confidence to portfolio. Implement auto-disable logic: if (enabled && n==0 && idle_hours>48) then disable.
- Idle strategies (enabled=true, n=0 trades, 48h+) are pure overhead. Implement auto-disable after 48h inactivity per standing order.
- Regime confidence <0.50 invalidates graduation gate progress. Calibration_edge success in low_vol_calm (0.57) is unreliable signal until regime stability improves.
- Capital constraint at $153.92 forces fractional Kelly to zero. Graduation readiness is theoretical only until balance supports minimum 1-contract positions across strategies.
- Idle strategies (enabled=true, n=0 trades, 48h+ inactivity) are cognitive load masquerading as optionality. Auto-disable per standing order to reduce false confidence.
- Regime confidence <0.50 invalidates graduation gate progress. Calibration_edge success in low_vol_calm (0.30 confidence) is unreliable signal until regime stability improves.
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
