-- Fix RLS policies: replace permissive USING(true) with service-role-only access.
-- The bot connects via SUPABASE_SERVICE_ROLE_KEY which bypasses RLS entirely,
-- so this locks out anon and authenticated roles without affecting bot operation.

-- ============================================================
-- Tables created in migrations (have existing permissive policies)
-- ============================================================

-- deepstack_positions
DROP POLICY IF EXISTS "Service role full access positions" ON deepstack_positions;
CREATE POLICY "Service role only positions"
  ON deepstack_positions FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_orders
DROP POLICY IF EXISTS "Service role full access orders" ON deepstack_orders;
CREATE POLICY "Service role only orders"
  ON deepstack_orders FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_fills
DROP POLICY IF EXISTS "Service role full access fills" ON deepstack_fills;
CREATE POLICY "Service role only fills"
  ON deepstack_fills FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_settlements
DROP POLICY IF EXISTS "Service role full access settlements" ON deepstack_settlements;
CREATE POLICY "Service role only settlements"
  ON deepstack_settlements FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- ============================================================
-- Tables created via Supabase dashboard (may lack RLS entirely)
-- Enable RLS first, then add service-role-only policy.
-- ============================================================

-- deepstack_bot_config
ALTER TABLE IF EXISTS deepstack_bot_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access bot_config" ON deepstack_bot_config;
CREATE POLICY "Service role only bot_config"
  ON deepstack_bot_config FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_bot_commands
ALTER TABLE IF EXISTS deepstack_bot_commands ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access bot_commands" ON deepstack_bot_commands;
CREATE POLICY "Service role only bot_commands"
  ON deepstack_bot_commands FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_trades
ALTER TABLE IF EXISTS deepstack_trades ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access trades" ON deepstack_trades;
CREATE POLICY "Service role only trades"
  ON deepstack_trades FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_strategy_status
ALTER TABLE IF EXISTS deepstack_strategy_status ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access strategy_status" ON deepstack_strategy_status;
CREATE POLICY "Service role only strategy_status"
  ON deepstack_strategy_status FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_dashboard_state
ALTER TABLE IF EXISTS deepstack_dashboard_state ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access dashboard_state" ON deepstack_dashboard_state;
CREATE POLICY "Service role only dashboard_state"
  ON deepstack_dashboard_state FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_log_entries
ALTER TABLE IF EXISTS deepstack_log_entries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access log_entries" ON deepstack_log_entries;
CREATE POLICY "Service role only log_entries"
  ON deepstack_log_entries FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- deepstack_opportunities
ALTER TABLE IF EXISTS deepstack_opportunities ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access opportunities" ON deepstack_opportunities;
CREATE POLICY "Service role only opportunities"
  ON deepstack_opportunities FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');
