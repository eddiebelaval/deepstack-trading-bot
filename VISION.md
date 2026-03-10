# VISION.md -- Living North Star
## DeepStack

> Last evolved: 2026-03-10 | Confidence: MEDIUM
> Distance from SPEC: 55% (6 of 11 pillars realized)

---

## Soul

DeepStack exists because the market is a conversation between fear and greed, and most retail traders are listening with a tin can. The thesis: prediction markets are the crowd's subconscious -- they price the future BEFORE capital markets react. If you can read the crowd's body language (Kalshi PM price velocity), synthesize it with traditional signals (IBKR stock data, TradingView backtests), and let the system regulate itself (governance, circuit breakers, adaptive parameters), you don't need to be the smartest trader. You need to be the most aware. DeepStack is a wealth generation engine that sees forward, learns from every trade, and governs itself -- not because AI replaces judgment, but because it processes faster than human reflexes allow.

## Pillars

1. **Prediction Market Alpha** -- REALIZED
   Calibration edge strategy exploits favorite-longshot bias on Kalshi. 92% win rate on 38+ trades. The only consistently profitable strategy. This is the foundational edge.

2. **Multi-Asset Coverage** -- PARTIAL (40%)
   IBKR adapter connects to stocks, futures, options. Five IBKR strategies built (stock_momentum, crisis_alpha, futures_trend, options_income, options_directional). Watchlist: 20 tickers including inverse ETFs, volatility products, safe havens, defense, oil. Blocked by IBKR connectivity -- strategies timeout-protected but untested with live market data.

3. **Forward Signal Intelligence** -- PARTIAL (30%)
   ForwardSignalBridge reads Kalshi PM price velocity as leading indicators. Signal taxonomy: RATE_SHIFT (KXFED), INFLATION (KXCPI), GROWTH (KXGDP), RISK_APPETITE (KXBTC/KXETH). Wired into governance engine for regime bias injection. Ingesting data every cycle. Not yet triggered -- needs volatile market conditions to exceed thresholds.

4. **Self-Governance** -- REALIZED
   MarketGovernor in autonomous mode. Regime detection (5 regimes). Lexicon signal generator. Strategy enable/disable actuators. Forward signal bias injection. Governance runs every cycle with fresh market data.

5. **Recursive Learning** -- REALIZED
   Bayesian win rate posteriors per strategy. Dynamic Kelly sizing from realized data. Adaptive take-profit/stop-loss from performance tracker. AI analysis every 30 min. Circuit breakers auto-disable bleeding strategies. Trade journal captures everything.

6. **Crisis Trading Readiness** -- PARTIAL (50%)
   crisis_alpha strategy built: inverse ETFs (SQQQ, SDOW, SH), volatility (UVXY), safe havens (GLD, TLT), geopolitical plays (USO, XLE, LMT, RTX, NOC). Regime-gated entry logic. Tighter stops for leveraged products. Built but untested -- needs IBKR connectivity and actual crisis conditions.

7. **Options Intelligence** -- PARTIAL (30%)
   options_income (sold puts) and options_directional (bought puts/calls) strategies built. Regime-gated: puts in trending_down, calls in trending_up. ATM to 20% OTM, 14-45 DTE targeting. Built but untested -- needs IBKR options chain data.

8. **Graceful Degradation** -- REALIZED
   asyncio.wait_for timeouts on all 7 IBKR call sites. When IBKR is down, Kalshi strategies run unimpeded. Bot cycles complete in ~2 minutes regardless of IBKR state. No more infinite hangs.

9. **News Triangulation** -- UNREALIZED
   news_sentiment_fade strategy exists but disabled. Vision: synthesize prediction market signals + recent news + capital markets into forward-looking intelligence. News API integration not built.

10. **Graduation Gates** -- PARTIAL (40%)
    Config exists for per-asset-class graduation (Kalshi 50 trades/45% WR, stocks 30/50%, futures 20/45%, options 15/60%). graduation_gate.py only reads flat Kalshi config. Multi-asset gate code not implemented.

11. **Dashboard Intelligence** -- REALIZED
    v3 multi-page dashboard live at milo.deepstack.trade. 5 dedicated pages (Command Center, Operations, Intelligence, Graduation, Research). WeatherMap NOAA-style radar visualization. AnalyticsPanel with 6 chart views. Security-hardened API layer (PostgREST filter injection fixed, whitelist validation). 34 orphaned v2 components cleaned up. Terminal green-on-black aesthetic. Real-time Supabase sync. Telegram bridge for mobile alerts.

## User Truth

**Who:** Eddie Belaval, founder of id8Labs. One-person operation trading with $159.65 real capital and $2,000 paper balance.

**Before:** "Markets are moving because of Iran and I can't capitalize. I can only buy prediction market contracts. I can't short, I can't buy puts, I can't trade inverse ETFs. The bot finds zero opportunities for days. When it does trade, it loses."

**After:** "The bot sees forward through prediction markets, trades across asset classes, governs itself through regime changes, and learns from every trade. When crisis hits, it's already positioned. When markets are calm, it collects prediction market alpha."

## Edges

- DeepStack is NOT a high-frequency trading system. 60-second cycles, not microseconds.
- DeepStack does NOT trade with margin or naked options. Defined-risk only (bought options, inverse ETFs).
- DeepStack does NOT override circuit breakers. If a strategy bleeds, it stops.
- DeepStack does NOT graduate to live trading without passing data gates. Paper first, prove it, then graduate.
- DeepStack is NOT dependent on any single data source. IBKR down? Kalshi strategies continue. News API down? Price-based signals still work.

---

*Private -- id8Labs LLC*
