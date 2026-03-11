-- Paper trade isolation + dashboard balance freshness.
--
-- 1. Add is_paper to deepstack_trades so paper trades are explicitly
--    flagged and filterable (safety net — paper trades already skip
--    Supabase push, but this prevents future regressions).
--
-- 2. Add balance_source to deepstack_dashboard_state so we can
--    distinguish between trading-cycle pushes and startup/shutdown
--    balance syncs.
--
-- 3. Backfill existing paper trades by order_id prefix and metadata.

-- is_paper column on trades
ALTER TABLE deepstack_trades
  ADD COLUMN IF NOT EXISTS is_paper BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_deepstack_trades_is_paper
  ON deepstack_trades(is_paper);
-- balance_source on dashboard_state (startup_sync, shutdown_sync, trading_cycle)
ALTER TABLE deepstack_dashboard_state
  ADD COLUMN IF NOT EXISTS balance_source TEXT DEFAULT 'trading_cycle';
-- Backfill: mark existing paper trades by order_id prefix
UPDATE deepstack_trades SET is_paper = TRUE WHERE order_id LIKE 'paper-%';
-- Backfill: mark by metadata JSON field
UPDATE deepstack_trades SET is_paper = TRUE
  WHERE metadata->>'paper_trade' = 'true' AND is_paper = FALSE;
