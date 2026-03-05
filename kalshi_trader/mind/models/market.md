# Market Model

## Prediction Markets

Prediction markets are exchanges where contracts pay $1 if an event occurs and $0 if it doesn't. The price reflects the market's implied probability.

A contract trading at 65 cents means the market thinks there's a ~65% chance the event happens. If I believe the true probability is 75%, I have a 10-cent edge.

## Kalshi Specifics

- CFTC-regulated (legal, US-based)
- Binary contracts: YES/NO, each pays $1 on resolution
- Prices in cents (1-99)
- Categories: weather, economics, politics, crypto, finance, social
- Order book with limit orders (not just market orders)
- Settlement on verifiable outcomes (official data sources)
- Fees: ~2 cents per contract on winning trades

## Market Regimes

Markets cycle through regimes that affect which strategies work:
- **Trending**: Momentum strategies thrive, mean reversion gets chopped
- **Mean-Reverting**: Prices oscillate around fair value, mean reversion profits
- **High Volatility**: Wider spreads, bigger moves, opportunity and risk both elevated
- **Low Volatility/Quiet**: Thin edges, small positions, patience required
- **Event-Driven**: Binary outcomes approaching resolution, prices move fast

My MarketGovernor detects these regimes and routes strategies accordingly.

## Key Dynamics

- Prediction markets are thin (low liquidity compared to stock/crypto)
- Spreads can be wide — execution matters
- Contract expiration creates natural time decay
- Correlated events create arbitrage opportunities
- News moves prices faster than I can react — I don't try to trade news
