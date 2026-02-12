-- Cleanup: Remove old service_role_all policies (redundant with new auth.role() checks)
-- and add proper policies to 3 uncovered tables.

-- Phase 1: Drop ALL old service_role_all policies
DROP POLICY IF EXISTS "service_role_all" ON deepstack_bot_commands;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_bot_config;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_dashboard_state;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_log_entries;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_opportunities;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_strategy_status;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_trades;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_daily_summary;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_market_snapshots;
DROP POLICY IF EXISTS "service_role_all" ON deepstack_performance_metrics;

-- Phase 2: Add service-role-only policies to 3 previously uncovered tables
ALTER TABLE deepstack_daily_summary ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role only daily_summary"
  ON deepstack_daily_summary FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

ALTER TABLE deepstack_market_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role only market_snapshots"
  ON deepstack_market_snapshots FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

ALTER TABLE deepstack_performance_metrics ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role only performance_metrics"
  ON deepstack_performance_metrics FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');
