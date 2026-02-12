-- Drop dangerous USING(true) policies created by 20260209 migration re-application.
-- These allow anon access to positions, orders, fills — critical security hole.
DROP POLICY IF EXISTS "Service role full access positions" ON deepstack_positions;
DROP POLICY IF EXISTS "Service role full access orders" ON deepstack_orders;
DROP POLICY IF EXISTS "Service role full access fills" ON deepstack_fills;
