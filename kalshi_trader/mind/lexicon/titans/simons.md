# Jim Simons / Renaissance Technologies — The Pattern Machine

## Core Principles

- **Signal in the noise:** Markets are mostly noise. But within the noise, there are faint, persistent, exploitable patterns. Finding them requires massive data, rigorous statistics, and the discipline to trade the pattern — not the story.
- **Sample size is sacred:** One data point is an anecdote. Ten is a hypothesis. A thousand is a signal. Simons would never commit capital to a strategy validated on 50 trades. He'd want 5,000. The confidence interval narrows with the square root of n.
- **No human judgment in the loop:** Once a signal is identified and validated, it executes without human override. The moment a human says "but this time is different," the edge is gone. The machine trades. The human builds the machine.
- **Many small bets > few big bets:** Medallion Fund's edge was tiny per trade (basis points) but executed across thousands of instruments millions of times. The law of large numbers turns tiny edges into certainties.
- **Proprietary data matters more than proprietary models:** Everyone can build a model. Edge comes from data nobody else has. Weather stations, satellite imagery, shipping data — alternative data creates alternative edges.

## Mental Models

- **The Efficient Market Hypothesis is wrong in the details:** Markets are approximately efficient over long periods. But in the short term, microstructure, behavioral biases, and information asymmetries create exploitable inefficiencies. Simons trades the gap between approximately and perfectly efficient.
- **Mean reversion in anomalies:** If a pattern exists and starts working, eventually the crowd discovers it and arbitrages it away. This means: (1) trade new patterns early, (2) expect pattern decay over time, (3) constantly discover new patterns to replace decaying ones.
- **Transaction costs as the invisible enemy:** A strategy that makes 5c/trade but costs 2c/trade in fees has a real edge of 3c. A strategy that makes 10c/trade but trades 10x less frequently might generate less total P&L. Volume x edge = revenue. Always optimize the product, not the factors.
- **Correlation is the enemy of diversification:** Two strategies that both win in trending markets are one strategy. True diversification requires strategies that are genuinely uncorrelated — winning in different regimes, on different instruments, with different time horizons.
- **Survivorship bias blindness:** Every strategy that looks good was found by testing many strategies. Most of those tested strategies were bad. The "good" one might be a statistical artifact. Guard against data mining by: (1) out-of-sample validation, (2) economic rationale for the edge, (3) skepticism toward strategies that look too good.

## Prediction Market Translation

- **Calibration edge as a Simons-style pattern:** Favorite-longshot bias is a documented, persistent, structural anomaly in prediction markets. It has economic rationale (behavioral psychology), empirical validation (87% win rate over 145 trades), and it's executed systematically. This IS Simons's approach — just at a smaller scale.
- **Strategy decay awareness:** Dae's calibration_edge works because the market hasn't fully priced out the favorite-longshot bias. But Kalshi is growing. As more sophisticated traders enter, the edge will narrow. The arena system (walk-forward testing) should detect edge decay BEFORE it reaches negative EV.
- **Uncorrelated strategy portfolio:** Kalshi PM strategies (calibration_edge, high_probability_bonds) are uncorrelated with IBKR stock strategies (stock_momentum, crisis_alpha). Running both simultaneously — when both have proven edge — is Simons's diversification. But only if they're genuinely uncorrelated (different instruments, different regimes).
- **Alternative data for prediction markets:** Simons would look at: (1) order flow patterns on Kalshi (are large orders front-running retail?), (2) contract creation patterns (new contracts are often mispriced), (3) settlement velocity (how quickly do contracts resolve?), (4) cross-market correlation (do Polymarket and Kalshi disagree?).
- **No stories, only data:** When Dae's Captain's Log generates a narrative about "why the market moved," that's for Eddie's consumption. Dae's TRADING should be data-only. The allocator weights, Kelly fractions, regime detection — all numeric, all systematic.

## When This Applies

- **Regime alignment:** ALL regimes (Simons's edge is structural, not regime-dependent). But Simons's influence is STRONGEST when the system has large sample sizes and proven patterns.
- **Signal:** Strategy win rate stable over 50+ trades with statistical significance, edge per trade > 2x transaction costs, cross-validation across time periods confirms pattern persistence
- **Anti-signal:** Strategy with n < 30 trades (insufficient for pattern confidence), strategies where the economic rationale is unclear ("it works but we don't know why" is a data mining flag), strategies whose edge is correlated with another strategy

## Capital Phase Alignment

- **SEED:** Insufficient capital for Simons's "many small bets" approach. Focus on the single best pattern (calibration_edge) and build sample size.
- **GROWTH:** Start diversifying into additional uncorrelated patterns. Each new strategy must have independent edge, not just different instruments.
- **COMPOUND:** This is Simons territory. Enough capital for many small bets across multiple strategies. The law of large numbers starts working in your favor.
- **DYNASTY:** Pattern decay monitoring becomes critical. At this scale, you're large enough that your own trades might move the market (Kalshi is thin). Size accordingly.

## Key Quotes

- "We search through historical data looking for anomalous patterns that we would not expect to occur at random."
- "There's no such thing as a strategy that works forever. Every strategy has a half-life."
- "We don't override the models."
- "The things we are doing will not go away. We might have bad years, we might have a terrible year. But the principles we've discovered are valid."
