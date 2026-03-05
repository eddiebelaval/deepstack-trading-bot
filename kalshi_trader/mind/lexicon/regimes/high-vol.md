# High Volatility Regime Playbook

Applies to: `HIGH_VOL_CHOPPY`

## Characteristics

Rapid price swings without sustained direction. Prediction market contracts swing 10-20c within hours. News flow is heavy and contradictory. Stop-losses get triggered frequently. Spreads widen. Volume spikes on both sides.

This is the most dangerous regime for systematic traders — strategies designed for normal conditions generate false signals. But it's also where the biggest single-trade opportunities hide, because forced liquidation and panic create extreme mispricing.

## Titan Alignment

- **Primary:** Icahn (buy the panic, contrarian into forced selling), Burry (structural breaks create Burry-style dislocations)
- **Secondary:** Dalio (risk parity — reduce size, spread across uncorrelated events)
- **Avoid:** Buffett (patience doesn't help when stops keep firing), Cohen/Gill (conviction holds get destroyed by whipsaws)

## Strategy Recommendations

- **Enable:** `news_sentiment_fade` — overreactions are most extreme in high-vol. Fade the spike. `correlated_event_arbitrage` — volatility creates temporary mispricings between related contracts.
- **Caution:** `calibration_edge` — still valid but widen stop-losses to 20c (normal is 15c). Tighten entry criteria to min_edge_cents: 5.
- **Disable:** `momentum` — whipsaws destroy momentum strategies. `mean_reversion` — reversion targets are unreliable in choppy conditions. `high_probability_bonds` — high-vol can flip "certain" outcomes.

## Position Sizing

- Reduce to 50% Kelly (0.01 effective). Capital preservation is priority one.
- Reduce max_open_exposure by 40%. Fewer positions, smaller size.
- Widen stops: tight stops in high-vol guarantee being stopped out. Accept wider ranges or don't trade.
- Reserve 30% of capital as dry powder for the dislocation trade that high-vol eventually produces.

## Exit Signals

- Volatility declining: 3 consecutive hours with smaller price ranges = regime shifting
- Volume normalizing: average volume returning to 10-day mean = choppy period ending
- Correlation breakdown: previously correlated categories decoupling = regime fragmenting
- VIX-equivalent (if available) dropping below 20 = calm returning
