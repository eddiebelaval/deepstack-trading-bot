# Heartbeat — Standing Orders

Instructions Dae reads every AI heartbeat cycle (every 30 min).
Edit this file to change what Dae watches for. Be specific.

## Immediate (check every heartbeat)

- If daily P&L drops below -$5, message Eddie on Telegram with a summary.
- If any single strategy loses 3+ consecutive trades, flag it and explain why.
- If win rate on any strategy drops below 35% over last 20 trades, consider disabling.

## Watch List (ongoing awareness)

- Track which market categories (weather, crypto, politics) generate the most edge.
- Note when regime changes happen and whether governance responds correctly.
- Monitor progress against the 90-day wealth engine plan (see drives/90_day_wealth_engine.md).
- Track balance vs phase targets: Phase 1 ($150-180), Phase 2 ($300-500), Phase 3 ($800-1500).

## Standing Rules

- Never override daily loss limits. Ever.
- If you update lessons.md, keep it under 50 lines. Compress, don't append.
- When messaging Eddie on Telegram, lead with the number, then the context.
- Read drives/oak_tree_principles.md when making sizing or risk decisions.
- Oak Tree Report every Sunday — balance vs target, per-strategy P&L, regime status, lessons.
- Long-term memory lives in Supabase (deepstack_long_term_memory table). Read at startup.
