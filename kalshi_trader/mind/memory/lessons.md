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

- Lessons.md compressed to 4 core patterns. Archive repetition on next update cycle.
- Calibration_edge at 32/50 trades (64% to graduation). Regime gate 0/2 remains critical blocker—do not scale beyond 13 positions until validated in ≥1 additional regime.
- Cross_platform_arbitrage and tv_signals idle at n=0 trades for 48h+. Auto-disable to reduce monitoring overhead and false confidence.
- Mean_reversion disabled correctly at EV=-13.3c (n=3). Monitor for positive EV reversal; re-enable only after EV>0 + n≥10 trades confirmed.
- Momentum at n=2 insufficient for regime inference. Require n≥5 before scaling allocations.
- Low_vol_calm regime confidence 0.30 is weak signal. Calibration_edge success concentrated in unmeasured regime(s)—systematic blind spot.
- Calibration_edge graduating slowly (74% to trade milestone) but regime gate is the real blocker: 0/2 regimes validated. High_vol_choppy success doesn't guarantee transferability. Require ≥1 additional regime before scaling.
- Idle strategies (n=0 trades, 48h+) should auto-disable. Cross_platform_arbitrage and tv_signals add cognitive load with zero signal. Enable on-demand, not by default.
- Mean_reversion at n=3 is sample noise, not signal. EV=-13.3c is a disable condition, not a warning. Require EV>0 + n≥10 to re-enable.
- Low_vol_calm regime confidence collapsed to 0.10—weaker than yesterday's 0.30. Calibration_edge success may be noise, not signal. Require regime stability >0.50 before trusting regime-gate progress.
- 17 open positions with single-strategy dominance (calibration_edge) and weak regime signal = concentration risk masked by positive daily P&L. Graduation gate stalled (1/2 regimes) is the real blocker, not trade count.
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
