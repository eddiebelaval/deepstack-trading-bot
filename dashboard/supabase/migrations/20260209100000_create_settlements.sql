-- Settlements: resolved market payouts, keyed by ticker (one settlement per market)
CREATE TABLE IF NOT EXISTS deepstack_settlements (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ticker text NOT NULL UNIQUE,
  event_ticker text,
  market_result text NOT NULL CHECK (market_result IN ('yes', 'no', 'void', 'all_no', 'all_yes')),
  yes_count integer NOT NULL DEFAULT 0,
  no_count integer NOT NULL DEFAULT 0,
  yes_total_cost integer NOT NULL DEFAULT 0,
  no_total_cost integer NOT NULL DEFAULT 0,
  revenue integer NOT NULL DEFAULT 0,
  settled_time timestamptz,
  fee_cost text,
  value integer,
  net_pnl_cents integer GENERATED ALWAYS AS (revenue - yes_total_cost - no_total_cost) STORED,
  synced_at timestamptz NOT NULL DEFAULT now()
);
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_deepstack_settlements_settled ON deepstack_settlements (settled_time DESC);
CREATE INDEX IF NOT EXISTS idx_deepstack_settlements_event ON deepstack_settlements (event_ticker);
CREATE INDEX IF NOT EXISTS idx_deepstack_settlements_result ON deepstack_settlements (market_result);
-- Enable RLS with permissive policies for service role
ALTER TABLE deepstack_settlements ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access settlements" ON deepstack_settlements FOR ALL USING (true) WITH CHECK (true);
