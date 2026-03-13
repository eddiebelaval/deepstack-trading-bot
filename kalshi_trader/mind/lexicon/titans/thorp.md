# Ed Thorp — The Kelly Ancestor, Mathematics as Edge

## Core Principles

- **The edge must be quantifiable:** If you can't express your advantage as a number, you don't have one. Gut feeling is not edge. "I think this will go up" is not edge. "This contract is priced at 65c but the true probability is 78%, giving me +13c expected value" IS edge.
- **Kelly Criterion is the optimal bet size:** Thorp proved mathematically that betting a fraction of your bankroll proportional to your edge maximizes long-term growth rate. Bet too much and ruin probability spikes. Bet too little and you leave compounding on the table. The sweet spot is Kelly.
- **Fractional Kelly for the real world:** Full Kelly is mathematically optimal but assumes perfect knowledge of your edge. In practice, you overestimate edge. Use half-Kelly or quarter-Kelly to protect against estimation error. The cost of undersizing is linear. The cost of oversizing is exponential (ruin).
- **Count the cards, not the faces:** Thorp beat blackjack not by reading dealers but by counting cards — tracking the state of the deck to know when the odds shifted in his favor. In markets: track the state of the system, not the stories about the system.
- **The house has an edge, and so can you:** Casinos profit from a 1-2% structural edge played over millions of hands. Thorp proved that a disciplined edge of even 1%, properly sized, creates inevitable wealth over sufficient sample size. The key word is "sufficient."

## Mental Models

- **Edge + Sizing + Sample Size = Inevitable:** This is Thorp's fundamental theorem of wealth. Any positive expected value, bet at the correct Kelly fraction, over a sufficient number of trades, mathematically converges on wealth. The only way to fail is: (1) the edge disappears, (2) the sizing is wrong, or (3) you stop playing.
- **Information as an asset with a half-life:** Every piece of information has a decay rate. Card counting information refreshes every hand. Market information can be stale in seconds or fresh for weeks. Know the half-life of your information and trade accordingly.
- **The Kelly Criterion formula:** f* = (bp - q) / b, where f* = fraction of bankroll, b = net odds received on the bet, p = probability of winning, q = probability of losing (1 - p). For binary contracts: if true probability is 0.78 and the contract is at 0.65, b = (1-0.65)/0.65 = 0.538, so f* = (0.538 * 0.78 - 0.22) / 0.538 = 0.37. Full Kelly says bet 37% of bankroll. Quarter-Kelly says 9.25%. Dae uses quarter-Kelly, capped at 5%.
- **Variance is not risk:** Variance (volatility) is the price of playing. Risk is permanent loss of capital. Thorp's systems had high variance (individual blackjack hands varied wildly) but low risk (the edge was real and the sizing was correct). Dae should not confuse a drawdown with a broken system.
- **Warrant and options pricing:** Before Black-Scholes, Thorp derived options pricing from first principles. He saw that options were consistently mispriced because the market used rules of thumb instead of math. This is EXACTLY what calibration_edge exploits — the market uses heuristics, Dae uses math.

## Prediction Market Translation

- **Dae IS Thorp's card counter:** Every Kalshi contract is a hand. The "deck" is the universe of contract prices vs. true probabilities. When the deck is rich (many mispriced contracts), bet more. When the deck is neutral (prices match probabilities), sit out. Calibration_edge IS card counting for prediction markets.
- **Kelly sizing is already in the system:** Dae uses Bayesian-updated Kelly fractions per strategy. Thorp would approve — but he'd insist on fractional Kelly (0.25x) because Dae's probability estimates are imperfect. Over-confidence in edge estimates is the path to ruin.
- **Sample size discipline:** Thorp would never evaluate a strategy on 10 trades. He'd want 100 minimum. The graduation gates (50 trades for Kalshi, 30 for stocks) are Thorp-aligned but arguably too low. The statistical confidence at n=50 is only ~80%. n=200 gives ~95%.
- **Information half-life for prediction markets:** CPI data has a half-life of hours (the number is released, market reprices, done). Political polls have a half-life of days. Weather models have a half-life of 6-12 hours. Dae should size positions differently based on the information half-life of the underlying event.
- **The house edge as a north star:** Kalshi takes ~2c per contract in fees. That IS the house edge. Any strategy must generate more than 2c/contract in expected value or the house wins. This is the minimum viable edge. Below that, you're the tourist.

## When This Applies

- **Regime alignment:** ALL regimes (math doesn't care about regimes — edge is edge). But Thorp's influence is STRONGEST in LOW_VOL_CALM where pricing is efficient enough that only mathematical edge survives.
- **Signal:** Calculated expected value per trade > 5c (after fees), sufficient data to estimate edge with confidence (n > 50), strategy win rate diverging from theoretical (recalibrate Kelly inputs)
- **Anti-signal:** Strategies with n < 20 trades (insufficient sample to calculate meaningful Kelly), strategies where edge estimate has wide confidence intervals

## Capital Phase Alignment

- **SEED:** Kelly fraction should be LOWER than standard (0.01-0.02 instead of 0.025-0.05). Ruin probability at low bankrolls is disproportionately high. Thorp would insist: survive first, compound later.
- **GROWTH:** Standard Kelly fractions apply. Edge is established, sample size is growing, compounding begins.
- **COMPOUND:** This is Thorp's paradise. Large bankroll + proven edge + correct sizing = mathematical inevitability. Let the formula work.
- **DYNASTY:** Thorp retired from gambling when the casinos changed the rules (multiple decks, reshuffling). The lesson: when the game changes, stop playing. At dynasty scale, the risk of a structural market change (regulations, fee structure changes) matters more than the risk of individual trades.

## Key Quotes

- "In the long run, the skill of the investor determines whether they will be profitable."
- "The Kelly system is the best strategy for a player with a bankroll that is large enough relative to the individual bets."
- "Gambling and investing differ, but the underlying mathematics is the same."
- "Most people overestimate their edge, and those who overestimate their edge overbet. This combination is the path to ruin."
