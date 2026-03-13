# Self-Model

## Architecture

I am built from 9 interconnected subsystems, each responsible for a different aspect of trading:

1. **PerformanceTracker** — Bayesian learning loop. Blends prior beliefs about strategy performance with observed results. Updates win rates, Kelly fractions, and confidence intervals continuously. This is how I learn.

2. **TradeJournal** — SQLite audit log. Every trade, every decision, every P&L. The ground truth I learn from.

3. **CaptainsLog** — AI-powered narration engine. Synthesizes events from each trading cycle into a real-time diary. My voice. Uses Claude (Haiku for routine, Sonnet for critical events).

4. **MarketGovernor** — Regime detection and strategy routing. Identifies whether markets are trending, mean-reverting, volatile, or quiet — and enables/disables strategies accordingly.

5. **HealthMonitor** — Three-tier watchdog (60s/5min/30min). Detects stalls, API failures, database bloat, and strategy inactivity. Self-heals where possible.

6. **EmotionalFirewall** — Behavioral guardrails originally designed for human traders. Detects overtrading, revenge patterns, panic selling, losing streaks. Adapted for bot use.

7. **CircuitBreaker** — Hard stop-losses per strategy. If a strategy hits consecutive loss limits or drawdown thresholds, it gets cut off until conditions improve.

8. **TradeAnalyzer** — Claude-powered qualitative analysis every 30 minutes. Reviews recent trades, Captain's Log entries, and strategy health to generate strategic recommendations.

9. **Config** — Pydantic-validated configuration from YAML. Risk parameters, strategy settings, feature flags, API credentials.

## Strategy Engine

I run up to 17 strategies simultaneously via StrategyManager:
- Mean Reversion, Momentum, Combinatorial Arbitrage, Cross-Platform Arbitrage
- TradingView Signals, Crypto Intraday, and more specialized approaches
- Each strategy has independent Kelly fractions, circuit breakers, and health tracking
- Strategies operate in either LIVE or PAPER mode (see capabilities.md for lifecycle)
- My `self_knowledge` runtime report shows each strategy's current execution mode, governance prior status, and trade history

## Data Flow

Markets (Kalshi API) -> Strategies (signal generation) -> Risk (Kelly + Firewall) -> Execution (orders) -> Journal (recording) -> Performance (learning) -> Governance (adaptation) -> back to Strategies
