# Self-Learning Feedback Loop

**Priority:** P2 — Compounds all other improvements
**Owner:** Claude
**Status:** Pending

---

## What?

Automated daily analysis that runs after each trading session:

### Daily Review Checklist (automated)
1. Which strategies made money today?
2. Which strategies lost money?
3. Review circuit breaker triggers — did any trip? Should any have tripped?
4. Check win rate trends (7-day rolling, 30-day rolling)
5. Identify parameter drift — entry thresholds, stop sizes shifting?
6. Flag emotional overrides — did I manually re-enable a breaker-tripped strategy? How'd that go?
7. What was the market regime? (trending, ranging, volatile, dead)

### Auto-Adjust Scope (MVP — deliberately narrow)

**Auto-adjust (math-driven, safe to automate):**
- Kelly fractions — pure math from win rate + avg win/loss ratio, no human judgment needed

**Human review required (NOT auto-adjusted in MVP):**
- Entry thresholds
- Stop sizes
- Signal weights
- Strategy enable/disable (circuit breakers handle emergency disable; re-enable is human)

**Why narrow?** Kelly is a formula. You feed it data, it gives you a number. Entry thresholds and signal weights involve market intuition that we don't have enough data to automate yet. Automating those prematurely = compounding bad assumptions. Start with what's provably correct, expand later.

### Implementation
- Daily cron job or launchd task (fits HYDRA pattern)
- Results written to `workspace/prep/` as daily reports
- Summary pushed to Telegram
- Parameter changes applied to next session's config
- All changes reversible — keep history of parameter evolution

## Why?

Without a feedback loop, the bot makes the same mistakes forever. The 17.4% win rate should trigger automatic investigation: are the signals bad? Is the sizing wrong? Is the market regime unfavorable? Right now a human has to notice, diagnose, and fix. The loop should at least surface the problems automatically, even if human confirms the fix.

## Done When?

- [ ] Daily report generates automatically after trading session ends
- [ ] Report identifies top winner and top loser strategy with reasoning
- [ ] False signal rate tracked per strategy (signals that triggered but lost)
- [ ] Parameter history table — can see how thresholds evolved over time
- [ ] Telegram summary of daily performance lands in chat
- [ ] Kelly fractions auto-adjust based on rolling win rate data (MVP scope — only math-driven params)
- [ ] Entry thresholds, stop sizes, signal weights flagged for human review (not auto-adjusted)
