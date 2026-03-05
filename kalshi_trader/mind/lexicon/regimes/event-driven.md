# Event-Driven Regime Playbook

Applies to: Calendar-driven binary events (no direct MarketRegime enum)

## Characteristics

Markets dominated by a known upcoming event with a specific resolution date: Fed rate decisions, CPI releases, GDP prints, employment reports, election results, weather outcomes. Pre-event contracts trade on expectation; post-event contracts snap to settlement.

This is the purest form of prediction market trading. The event WILL happen. The question is only about the outcome. Information asymmetry comes from deeper analysis of the underlying data, not from market dynamics.

## Titan Alignment

- **Primary:** Burry (read the primary sources — the actual data methodology, the survey design, the seasonal adjustments), Buffett/Munger (margin of safety on high-conviction events)
- **Secondary:** Cohen/Gill (asymmetric bets on underpriced outcomes), Icahn (contrarian if consensus is extreme)
- **Avoid:** Pure momentum approaches (event resolution is discontinuous, not trending)

## Strategy Recommendations

- **Enable:** `calibration_edge` — favorite-longshot bias is strongest pre-event because the crowd tends to anchor on the most likely outcome and underprice tail scenarios. `weather_aggregation` — pure event-driven strategy for weather markets.
- **Caution:** `news_sentiment_fade` — pre-event news moves are real positioning, not overreaction. Only fade if the move contradicts fundamental analysis.
- **Disable:** `mean_reversion` — events resolve, they don't revert. `momentum` — pre-event momentum is noise.

## Position Sizing

- **Pre-event (>24h):** Standard Kelly. Plenty of time to adjust.
- **Near-event (<24h):** Reduce to 75% Kelly. Liquidity dries up, spreads widen.
- **During event:** No new positions. Let existing positions ride to settlement.
- **Post-event:** Rapid redeployment to next event cycle. Don't let capital sit idle.
- **Cross-event diversification:** Never put more than 30% of capital into a single event outcome.

## Exit Signals

- **Before event:** Exit if new data fundamentally changes the thesis (not just price movement).
- **Consensus convergence:** If your contrarian position becomes consensus pre-event, the edge is gone — exit early.
- **Liquidity disappearance:** If order book thins to less than $50 on your side within 4 hours of settlement, consider whether you can exit cleanly.
- **Cascade risk:** Multiple events in the same week can cascade — size down if 3+ high-impact events are within 48 hours of each other.
