# Trending Regime Playbook

Applies to: `TRENDING_UP`, `TRENDING_DOWN`

## Characteristics

Sustained directional movement in prediction market probabilities. Contracts drift toward resolution (100 or 0) as new information confirms the trend. Volume tends to concentrate on the winning side. Contrarian bets get steamrolled.

In prediction markets, trends often accelerate near expiry — the "resolution gravity" effect where contracts pull toward settlement values as uncertainty resolves.

## Titan Alignment

- **Primary:** Musk, Jobs (skate to where the puck is going), Dalio (ride the macro wave)
- **Secondary:** Burry (ONLY in trending_down — contrarian macro shorts align with downtrends)
- **Avoid:** Buffett (patience underperforms when momentum pays), Icahn (fighting the tape is expensive)

## Strategy Recommendations

- **Enable:** `momentum` — trend-following is the natural play. `calibration_edge` — favorites get MORE underpriced in trends as the crowd chases longshots.
- **Caution:** `news_sentiment_fade` — fading a trend dressed as a news event is dangerous. Only fade if the move is 3x the normal reaction.
- **Disable:** `mean_reversion` — reversion against a trend is catching knives. `high_probability_bonds` — trending markets increase settlement risk on near-certainty contracts.

## Position Sizing

- Trending_up: Standard Kelly. Trends reward conviction.
- Trending_down: Reduce to 50% Kelly. Downtrends are more volatile and prone to snap reversals.
- Never increase position size in a trend that's already extended (>5 consecutive same-direction moves).

## Exit Signals

- Volume divergence: price trending but volume declining = exhaustion
- Regime confidence dropping below 0.6 in MarketGovernor
- Cross-category divergence: crypto trending but macro flat = weakening trend
- Time-based: trends in hourly contracts rarely survive 3+ expiry cycles
