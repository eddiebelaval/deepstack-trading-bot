-- Add learning/performance columns to strategy_status table.
-- These columns carry the bot's Bayesian learning stats (blended win rate,
-- confidence, EV, health) so the dashboard can display real performance
-- data instead of relying on the broken settlement-based net_pnl_cents.
--
-- All columns are nullable so existing rows and older bot versions
-- continue to work without modification.

ALTER TABLE deepstack_strategy_status
  ADD COLUMN IF NOT EXISTS blended_win_rate DECIMAL(6,4),
  ADD COLUMN IF NOT EXISTS learning_confidence DECIMAL(6,4),
  ADD COLUMN IF NOT EXISTS effective_trades DECIMAL(8,1),
  ADD COLUMN IF NOT EXISTS blended_ev_cents DECIMAL(10,2),
  ADD COLUMN IF NOT EXISTS health_status TEXT DEFAULT 'unknown';
