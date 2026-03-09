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

- High_vol_choppy regime confidence 0.66 (down from 0.80)—regime shift risk weakening but calibration_edge still single-regime dependent. Graduation gate requires 2+ regimes; current progress 0/2.
- Four enabled strategies (mean_reversion, cross_platform_arbitrage, tv_signals, momentum) with n≤3 trades and negative or zero EV are monitoring dead weight. Disable until n≥5 + positive EV threshold met.
- Calibration_edge carries entire bot profitability (EV=315.3c, 28/50 trades). Graduation gate regime validation is critical—do not scale beyond 10 positions until 2+ profitable regimes demonstrated.
- Calibration_edge dominates profitability (EV=315.2c from 28 trades). Regime concentration in high_vol_choppy creates single-point-of-failure risk—graduation gate (0/2 regimes) is binding constraint.
- Four enabled strategies with n≤3 trades (mean_reversion n=3 EV=-13.7c, cross_platform_arbitrage n=0, tv_signals n=0, momentum n=2) generate no edge signal. Dead weight monitoring overhead—disable until n≥5 + positive EV threshold.
- Mean_reversion EV=-13.7c at n=3 trades—below sample gate. Hold disabled until n≥10 and positive EV.
- Four enabled strategies (mean_reversion, cross_platform_arbitrage, tv_signals, momentum) with n≤3 trades and negative/zero EV are monitoring overhead—disable until n≥5 + positive EV threshold met.
- Calibration_edge dominates profitability (EV=315.2c, 28 trades). High_vol_choppy regime concentration (0.76 confidence) with graduation gate at 0/2 regimes = single-point-of-failure risk. Do not scale beyond 10 positions until 2+ regimes demonstrated.
- Four enabled strategies (mean_reversion, cross_platform_arbitrage, tv_signals, momentum) with n≤3 trades and negative/zero EV are monitoring dead weight—disable until n≥5 + positive EV threshold met.
- Calibration_edge dominates profitability (EV=315.2c, 28 trades). High_vol_choppy regime concentration (0.71 confidence) with graduation gate at 0/2 regimes = single-point-of-failure risk.
- Regime confidence declining (0.80→0.71)—shift risk increasing. Do not scale beyond 10 positions until 2+ regimes demonstrated.
- Calibration_edge dominates profitability (EV=315.2c, 28 trades). High_vol_choppy regime concentration (0.59 confidence, down from 0.71) with graduation gate at 0/2 regimes = single-point-of-failure risk. Do not scale beyond 10 positions until 2+ regimes demonstrated.
- Mean_reversion at n=3, EV=-13.7c—below sample gate. Hold disabled until n≥10 + positive EV reversal.
- Four enabled strategies (mean_reversion, cross_platform_arbitrage, tv_signals, momentum) with n≤3 trades and negative/zero EV are monitoring dead weight. Disable until n≥5 + positive EV threshold met.
- Calibration_edge carries 100% of current profitability (EV=315.1c, 28/50 trades). High_vol_choppy regime concentration (0.67 confidence) with graduation gate at 0/2 regimes = single-point-of-failure risk. Do not scale beyond 10 positions until 2+ regimes demonstrated.
- Regime confidence 0.60 is inflection point—below this, high_vol_choppy regime classification becomes unreliable. Escalate regime monitoring frequency.
- Enabled-but-unproven strategies (n≤3, negative EV) create false monitoring overhead without edge signal. Enforce disabled=True default; require n≥5 + positive EV to re-enable.
- Calibration_edge single-regime profitability + declining regime confidence = compounding risk. Do not scale positions until graduation gate reaches 1/2 regimes.
- Regime confidence 0.57 (down from 0.59)—approaching inflection point of unreliability. Escalate regime shift detection.
- 10 open positions at $2K balance = 20% position concentration. Graduation gate still 0/2 regimes; do not scale until gate progresses.
- Low_vol_calm regime (confidence=0.30) signals regime shift—calibration_edge historically profitable only in high_vol_choppy. Monitor for edge degradation.
- Five enabled strategies with zero trades (cross_platform_arbitrage, high_probability_bonds, news_sentiment_fade, tv_signals) consuming monitoring cycles without signal. Consider disabling until n≥5.
- 10 open positions at $2K balance with 0.30 regime confidence = concentration risk in unproven regime. Graduation gate 0/2 regimes—do not add positions until regime validation or gate progress.
- Regime confidence below 0.60 is inflection point—classification reliability degrades. Escalate regime shift detection and consider temporary strategy lock-down if confidence drops below 0.50.
- Enabled-but-unproven strategies (n≤3, EV≤0) create false monitoring overhead. Enforce disabled=True default; require n≥5 + positive EV threshold before re-enabling.
