-- Trades table: mirrors local SQLite trades, populated by dashboard_sync.py
-- Keyed by order_id for upsert. Dashboard analytics depends on this table.

CREATE TABLE IF NOT EXISTS deepstack_trades (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    market_ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    action TEXT NOT NULL,
    contracts INTEGER NOT NULL DEFAULT 1,
    entry_price_cents INTEGER NOT NULL DEFAULT 0,
    fill_price_cents INTEGER,
    exit_price_cents INTEGER,
    pnl_cents INTEGER,
    order_id TEXT UNIQUE,
    exit_order_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reasoning TEXT,
    exit_reason TEXT,
    strategy TEXT DEFAULT 'mean_reversion',
    session_date DATE,
    is_paper BOOLEAN DEFAULT false,
    metadata JSONB
);

-- Indexes for dashboard analytics queries
CREATE INDEX IF NOT EXISTS idx_trades_status ON deepstack_trades (status);
CREATE INDEX IF NOT EXISTS idx_trades_session_date ON deepstack_trades (session_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON deepstack_trades (strategy);
CREATE INDEX IF NOT EXISTS idx_trades_updated ON deepstack_trades (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_order_id ON deepstack_trades (order_id);

-- RLS: service role only
ALTER TABLE deepstack_trades ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_trades" ON deepstack_trades
    FOR ALL USING (auth.role() = 'service_role');
