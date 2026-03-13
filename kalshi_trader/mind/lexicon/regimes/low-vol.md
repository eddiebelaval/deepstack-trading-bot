# Low Volatility Regime Playbook

Applies to: `LOW_VOL_CALM`

## Characteristics

Narrow price ranges, low volume, contracts drifting slowly toward settlement. Market participants are comfortable with current probabilities. News flow is light or already priced in. Spreads are tight. Order books are thin but stable.

This is the patience regime. Edge exists but is small. The best strategy is capital preservation while waiting for conditions to change. Overtrading in low-vol is the #1 way to bleed away an account through commissions and tiny adverse moves.

## Titan Alignment

- **Primary:** Buffett/Munger (patience is the position — wait for fat pitches), Dalio (all-weather allocation, collect small edges across many positions)
- **Secondary:** Musk, Jobs (use downtime to build better systems, not more trades)
- **Avoid:** Icahn (no dislocations to exploit), Burry (contrarian plays need volatility to create entry points)

## Strategy Recommendations

- **Enable:** `calibration_edge` — small but consistent edge from favorite-longshot bias still works. `high_probability_bonds` — low-vol makes near-certainty contracts safer (less chance of upset).
- **Caution:** `news_sentiment_fade` — low-vol means small reactions, which means small edge and high transaction cost relative to expected profit.
- **Disable:** `momentum` — no momentum to follow. `correlated_event_arbitrage` — tight spreads mean arbitrage opportunities are below transaction cost.

## Position Sizing

- Standard Kelly but reduce trade FREQUENCY, not size. Fewer but better trades.
- Increase selectivity: raise min_edge_cents to 5 (from default 3). Only trade clear mispricing.
- Maximum patience: the best trade in low-vol is often no trade.
- Accumulate dry powder: this regime precedes volatility spikes. Cash is a position.

## Exit Signals

- Volume spike: sudden 3x+ increase in volume = new information arriving, regime shift imminent
- Correlation shift: previously uncorrelated categories starting to move together = macro force incoming
- Calendar events: known high-impact events (Fed meetings, CPI, NFP) break low-vol regimes
- Time-based: low-vol regimes in prediction markets rarely last more than 5-7 days before catalysts arrive
