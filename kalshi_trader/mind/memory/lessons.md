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
- In choppy markets, wider stops and reduced position sizes help avoid false breakouts
- Zero P&L with multiple positions suggests tight management or offsetting trades
- Idle-strategy auto-disable (enabled=true, n=0, 48h+ inactivity) is a standing order—implement it to reduce false confidence in portfolio composition.
- Regime confidence <0.50 makes graduation gate progress theoretical only. Kalshi regime diversity requirement (2 regimes) cannot be satisfied in single low-confidence regime.
- Balance at $115.71 vs Phase 1 floor ($150) creates fractional Kelly death spiral. Minimum 1-contract positions impossible across portfolio until $150+ recovered.
- Auto-disable idle strategies (enabled=true, n=0, 48h+ inactive) to reduce false confidence in portfolio composition.
- Balance below $150 creates fractional Kelly death spiral — minimum viable position ($1) cannot be guaranteed across strategies.
- Calibration_edge dominance (100% of trades) indicates portfolio is one-strategy-dependent. Diversification requires capital recovery to $150+.
- Regime confidence <0.70 on single regime invalidates multi-regime graduation gate. Require stable regime diversity before scaling.
- Fractional Kelly death spiral confirmed: balance at $115.71 locks minimum positions at $1, preventing diversification execution across 4 active strategies.
- Calibration_edge is 100% of realized trades (159/159). Portfolio concentration risk masked by 85% win rate—single-strategy dependency.
- High_vol_choppy regime (0.80 confidence) is only regime sampled. Graduation gate requires 2 profitable regimes; current data cannot satisfy multi-regime requirement.
- Five idle strategies (enabled=true, n=0 trades, 48h+ inactivity: correlated_event_arbitrage, high_probability_bonds, weather_aggregation, news_sentiment_fade, domain_specialization) are dead weight masquerading as optionality.
- Zero P&L on flat day with 17 open positions suggests tight risk management or offsetting trades—verify position structure to confirm active hedging vs passive holding.
