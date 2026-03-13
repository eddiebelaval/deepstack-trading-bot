# Mean-Reverting Regime Playbook

Applies to: `MEAN_REVERTING`

## Characteristics

Prediction market probabilities oscillate around a central value without sustained directional movement. Contracts trade in a range — moves toward extremes snap back. This is the most common regime for mature markets with balanced information flow.

Binary contracts in mean-reverting regimes tend to cluster in the 30-70c range, where neither outcome is dominant. Favorite-longshot bias is most exploitable here because prices keep returning to the zone where calibration edge thrives.

## Titan Alignment

- **Primary:** Buffett/Munger (buy the dip, margin of safety on reversion), Cohen, Gill (turnaround plays as prices revert from extremes)
- **Secondary:** Dalio (balanced allocation works when nothing trends)
- **Avoid:** Musk, Jobs (visionary plays need trends to validate), momentum strategies in general

## Strategy Recommendations

- **Enable:** `calibration_edge` — this is its home regime. Favorite-longshot bias is most persistent in range-bound conditions. `mean_reversion` — literally designed for this.
- **Caution:** `momentum` — false breakouts are common. Tighten stop-losses to 3c if enabled.
- **Disable:** None required — most strategies can operate in mean-reverting conditions with standard parameters.

## Position Sizing

- Standard Kelly (0.02). Mean-reverting regimes are the safest for full position sizing.
- Increase max positions: diversification works well when everything reverts — uncorrelated bets reduce portfolio variance.
- Scale into positions: buy more as price moves further from mean (Buffett's "be greedy when others are fearful" in miniature).

## Exit Signals

- Sustained breakout above/below the range (3+ consecutive closes beyond 2 standard deviations)
- Volume spike without reversion within 2 hours = potential regime shift to trending
- Correlation increase across categories = macro force overriding mean reversion
- MarketGovernor confidence for MEAN_REVERTING dropping below 0.5
