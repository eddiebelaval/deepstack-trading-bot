-- Positions: upserted each bot cycle, keyed by ticker
CREATE TABLE IF NOT EXISTS deepstack_positions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ticker text NOT NULL UNIQUE,
  market_title text,
  side text NOT NULL CHECK (side IN ('yes', 'no')),
  contracts integer NOT NULL DEFAULT 0,
  position integer NOT NULL DEFAULT 0,
  total_traded integer NOT NULL DEFAULT 0,
  market_exposure integer NOT NULL DEFAULT 0,
  realized_pnl integer NOT NULL DEFAULT 0,
  fees_paid integer NOT NULL DEFAULT 0,
  resting_orders_count integer NOT NULL DEFAULT 0,
  current_price integer,
  market_value_cents integer,
  avg_entry_price_cents integer,
  last_updated_ts timestamptz,
  synced_at timestamptz NOT NULL DEFAULT now()
);

-- Orders: upserted each bot cycle, keyed by order_id
CREATE TABLE IF NOT EXISTS deepstack_orders (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id text NOT NULL UNIQUE,
  ticker text NOT NULL,
  side text NOT NULL CHECK (side IN ('yes', 'no')),
  action text NOT NULL CHECK (action IN ('buy', 'sell')),
  type text NOT NULL DEFAULT 'limit' CHECK (type IN ('limit', 'market')),
  status text NOT NULL DEFAULT 'resting',
  yes_price integer,
  no_price integer,
  initial_count integer NOT NULL DEFAULT 0,
  remaining_count integer NOT NULL DEFAULT 0,
  fill_count integer NOT NULL DEFAULT 0,
  taker_fees integer NOT NULL DEFAULT 0,
  maker_fees integer NOT NULL DEFAULT 0,
  taker_fill_cost integer NOT NULL DEFAULT 0,
  maker_fill_cost integer NOT NULL DEFAULT 0,
  created_time timestamptz,
  last_update_time timestamptz,
  expiration_time timestamptz,
  synced_at timestamptz NOT NULL DEFAULT now()
);

-- Fills: append-only, keyed by fill_id
CREATE TABLE IF NOT EXISTS deepstack_fills (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fill_id text NOT NULL UNIQUE,
  order_id text,
  ticker text NOT NULL,
  side text NOT NULL CHECK (side IN ('yes', 'no')),
  action text NOT NULL CHECK (action IN ('buy', 'sell')),
  count integer NOT NULL DEFAULT 0,
  yes_price integer,
  no_price integer,
  is_taker boolean DEFAULT false,
  fee_cost text,
  created_time timestamptz,
  synced_at timestamptz NOT NULL DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_deepstack_positions_synced ON deepstack_positions (synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_deepstack_orders_status ON deepstack_orders (status);
CREATE INDEX IF NOT EXISTS idx_deepstack_orders_synced ON deepstack_orders (synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_deepstack_fills_created ON deepstack_fills (created_time DESC);
CREATE INDEX IF NOT EXISTS idx_deepstack_fills_ticker ON deepstack_fills (ticker);

-- Enable RLS — policies are managed by 20260212_fix_rls_policies.sql
ALTER TABLE deepstack_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_fills ENABLE ROW LEVEL SECURITY;
