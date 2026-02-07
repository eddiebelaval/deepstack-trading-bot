-- DeepStack RLS Migration
-- Enables Row Level Security on ALL deepstack_ tables.
-- Only the service_role key (used by the dashboard API routes and bot) can access data.
-- The anon key gets NO access, preventing direct browser-based Supabase queries.

-- ============================================================================
-- ENABLE RLS ON ALL TABLES
-- ============================================================================

ALTER TABLE deepstack_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_daily_summary ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_dashboard_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_strategy_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_log_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_market_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_performance_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_bot_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_bot_config ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- SERVICE ROLE POLICIES (full access for API routes + bot)
-- ============================================================================
-- The service_role bypasses RLS by default in Supabase, but we add explicit
-- policies so that if someone changes the default behavior, access is preserved.

CREATE POLICY "service_role_all" ON deepstack_trades FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_daily_summary FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_opportunities FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_dashboard_state FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_strategy_status FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_log_entries FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_market_snapshots FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_performance_metrics FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_bot_commands FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON deepstack_bot_config FOR ALL TO service_role USING (true) WITH CHECK (true);

-- No policies for anon or authenticated roles = zero access via public anon key
