# Auto-Disable on Failure Thresholds

**Priority:** P0
**Owner:** Claude + Eddie
**Status:** Pending

---

## What?

Per-strategy circuit breakers:

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Win rate | < 40% over last 20 trades | Auto-disable strategy |
| Consecutive losses | 5 in a row | Auto-disable strategy |
| Drawdown | > 10% from strategy peak | Auto-disable strategy |

When a breaker trips:
- Strategy is disabled immediately (no more orders)
- Alert sent via Telegram (include: strategy name, trigger reason, P&L at trip, **win rate last 10 trades: X%** for instant context on blip vs systemic failure)
- Event logged with timestamp, trigger reason, and P&L at time of trip
- Manual override to re-enable — but requires explicit confirmation, not silent re-enable

### Manual Override Logging

When a strategy is force-enabled via CLI after a breaker trip, log separately:
- Timestamp of override
- Which breaker was tripped (and when)
- Who overrode it (CLI vs dashboard)
- Strategy performance after override (track next 10 trades)

**Why track this?** If post-mortems show frequent breaker overrides, that's a pattern — either the breakers are too sensitive or we're being emotionally reckless. Override frequency is a meta-signal about our own discipline.

## Why?

Market making would have been stopped at ~$5 loss instead of bleeding to $10.83. Prevents a single bad strategy from tanking the whole portfolio. The bot had 23 trades at 17.4% win rate — a circuit breaker would have killed it after trade 8-10.

## Done When?

- [ ] Circuit breaker trips during backtest simulation (provably works)
- [ ] I get a Telegram alert when a breaker trips in live/paper mode
- [ ] Re-enabling requires explicit confirmation (CLI flag or dashboard button)
- [ ] Breaker state persists across restarts (Supabase or local state file)
- [ ] Each strategy tracks its own independent breaker state
