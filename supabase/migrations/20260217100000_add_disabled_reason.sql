-- Add disabled_reason tracking to strategy_status
-- Persists WHY a strategy was killed (win rate, drawdown, manual, etc.)

ALTER TABLE deepstack_strategy_status
  ADD COLUMN IF NOT EXISTS disabled_reason TEXT,
  ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS disabled_by TEXT DEFAULT 'manual';
