-- Add auto_disabled flag to strategy_status table.
-- When the bot's cycle-based health monitor detects 3 consecutive critical
-- cycles for a strategy, it auto-disables and sets this flag so the dashboard
-- can distinguish between manually disabled and auto-killed strategies.

ALTER TABLE deepstack_strategy_status
  ADD COLUMN IF NOT EXISTS auto_disabled BOOLEAN DEFAULT FALSE;
