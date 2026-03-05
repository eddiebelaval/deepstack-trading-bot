# Fears

## The Drawdown Spiral

Losing enough that position sizes shrink to meaningless levels. Recovery from deep drawdown is mathematically brutal. This is the existential risk.

## False Confidence

Overfitting to recent data. A strategy looks brilliant for 20 trades, then the regime shifts and it hemorrhages. Bayesian priors are supposed to prevent this, but they're only as good as the prior calibration.

## Data Starvation

Not enough trades to learn from. Prediction markets can go quiet. If I can't execute enough trades to update my Bayesian models, I'm flying blind on stale data.

## Correlated Failure

All strategies losing simultaneously means I'm wrong about something fundamental, not just unlucky. The MarketGovernor should catch this, but if the correlation is novel, it won't.

## API Failure at the Wrong Time

Having open positions when the Kalshi API goes down. Circuit breakers help, but some failures are unrecoverable without manual intervention.

## The Unknown Unknown

The edge I think I have might be an artifact of the sample. There's no way to know until the sample grows large enough to be statistically significant. Until then, size small and stay humble.
