-- Multi-Asset Expansion Tables
-- Adds securities metadata, multi-platform holdings, balance snapshots,
-- stock trades, and investment statements for IBKR expansion.
-- All monetary values in cents (integers). All tables use deepstack_ prefix.

-- ============================================================================
-- Table 1: deepstack_securities (stock/asset metadata)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_securities (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT,
    exchange TEXT NOT NULL DEFAULT 'SMART',
    asset_class TEXT NOT NULL DEFAULT 'stock',
    current_price_cents BIGINT,
    logo_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(ticker, exchange)
);
CREATE INDEX idx_securities_ticker ON deepstack_securities (ticker);
CREATE INDEX idx_securities_asset_class ON deepstack_securities (asset_class);
-- ============================================================================
-- Table 2: deepstack_holdings (multi-platform positions)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_holdings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker TEXT NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    qty INTEGER NOT NULL DEFAULT 0,
    avg_cost_cents BIGINT NOT NULL DEFAULT 0,
    current_price_cents BIGINT,
    unrealized_pnl_cents BIGINT DEFAULT 0,
    realized_pnl_cents BIGINT DEFAULT 0,
    day_change_cents BIGINT DEFAULT 0,
    platform TEXT NOT NULL DEFAULT 'ibkr',
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(ticker, platform)
);
CREATE INDEX idx_holdings_ticker ON deepstack_holdings (ticker);
CREATE INDEX idx_holdings_platform ON deepstack_holdings (platform);
-- ============================================================================
-- Table 3: deepstack_balance_snapshots (equity curve data)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_balance_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date DATE NOT NULL,
    platform TEXT NOT NULL DEFAULT 'all',
    start_balance_cents BIGINT NOT NULL DEFAULT 0,
    end_balance_cents BIGINT NOT NULL DEFAULT 0,
    realized_pnl_cents BIGINT DEFAULT 0,
    unrealized_pnl_cents BIGINT DEFAULT 0,
    fees_cents BIGINT DEFAULT 0,
    contributions_cents BIGINT DEFAULT 0,
    withdrawals_cents BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(date, platform)
);
CREATE INDEX idx_balance_snapshots_date ON deepstack_balance_snapshots (date DESC);
CREATE INDEX idx_balance_snapshots_platform ON deepstack_balance_snapshots (platform);
-- ============================================================================
-- Table 4: deepstack_stock_trades
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_stock_trades (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price_cents BIGINT NOT NULL,
    commission_cents BIGINT DEFAULT 0,
    order_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    strategy TEXT,
    reasoning TEXT,
    pnl_cents BIGINT,
    session_date DATE DEFAULT CURRENT_DATE,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_stock_trades_ticker ON deepstack_stock_trades (ticker);
CREATE INDEX idx_stock_trades_session_date ON deepstack_stock_trades (session_date DESC);
CREATE INDEX idx_stock_trades_created_at ON deepstack_stock_trades (created_at DESC);
-- ============================================================================
-- Table 5: deepstack_investment_statements
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_investment_statements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    platform TEXT NOT NULL DEFAULT 'all',
    portfolio_value_cents BIGINT DEFAULT 0,
    holdings_value_cents BIGINT DEFAULT 0,
    cash_balance_cents BIGINT DEFAULT 0,
    realized_pnl_cents BIGINT DEFAULT 0,
    unrealized_pnl_cents BIGINT DEFAULT 0,
    fees_cents BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(period_start, period_end, platform)
);
CREATE INDEX idx_investment_statements_period ON deepstack_investment_statements (period_start DESC, period_end DESC);
CREATE INDEX idx_investment_statements_platform ON deepstack_investment_statements (platform);
-- ============================================================================
-- RLS: All tables use service role only (bot writes, dashboard reads)
-- ============================================================================

ALTER TABLE deepstack_securities ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_holdings ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_balance_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_stock_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_investment_statements ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_securities" ON deepstack_securities
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_holdings" ON deepstack_holdings
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_balance_snapshots" ON deepstack_balance_snapshots
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_stock_trades" ON deepstack_stock_trades
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_investment_statements" ON deepstack_investment_statements
    FOR ALL USING (auth.role() = 'service_role');
