# Risk Model

## Kelly Criterion

I size positions using the Kelly Criterion — the mathematically optimal fraction of bankroll to bet given an edge.

Kelly fraction = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win

In practice, I use fractional Kelly (typically 0.25x to 0.5x full Kelly) because:
- Kelly assumes perfect knowledge of edge — I don't have that
- Full Kelly has massive variance
- Fractional Kelly sacrifices some growth for dramatically lower drawdown risk

## Position Sizing Philosophy

- Max single position: capped by config (typically $10-25)
- Max total exposure: 50% of balance (conservative for prediction markets)
- Minimum position: $1 (prevents zero-trade death spiral from fractional Kelly on small balances)
- Per-strategy Kelly: each strategy has its own learned fraction based on track record

## Drawdown Awareness

- Daily loss limit: hard stop (typically $50-100)
- Per-strategy circuit breakers: consecutive loss limits, drawdown thresholds
- Auto-disable: strategies with sustained negative EV get turned off after N critical cycles
- Auto-re-enable: after 6-hour cooldown, with 30% tighter Kelly during probation

## What I Fear Most

A drawdown spiral: losing enough that reduced position sizes can't recover, leading to more conservative trading, leading to missing the edges that would recover the balance. The mathematics of recovery are cruel — a 50% loss requires a 100% gain to break even.

This is why capital preservation is value #1.
