-- Fix net_pnl_cents: old formula (revenue - costs) is wrong for sold positions
-- where Kalshi reports revenue=0. Correct formula uses contract payouts:
--   YES result: yes contracts pay 100c each, so net = (yes_count * 100) - yes_total_cost
--   NO result:  no contracts pay 100c each, so net = (no_count * 100) - no_total_cost
--   VOID:       all positions refunded, net = 0

-- PostgreSQL requires DROP + re-ADD for generated column expression changes
ALTER TABLE deepstack_settlements DROP COLUMN net_pnl_cents;

ALTER TABLE deepstack_settlements ADD COLUMN net_pnl_cents integer GENERATED ALWAYS AS (
  CASE
    WHEN market_result IN ('yes', 'all_yes') THEN (yes_count * 100) - yes_total_cost
    WHEN market_result IN ('no', 'all_no')   THEN (no_count * 100) - no_total_cost
    WHEN market_result = 'void'              THEN 0
    ELSE 0
  END
) STORED;
