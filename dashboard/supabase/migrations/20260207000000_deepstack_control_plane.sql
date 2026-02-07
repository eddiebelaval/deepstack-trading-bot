-- DeepStack Control Plane Migration
-- Migration 002: Move to Supabase with deepstack_ prefix + command/config tables
--
-- Run this on the id8labs Supabase project.
-- All tables prefixed with deepstack_ to avoid collision with Homer tables.

-- ============================================================================
-- TRADES (migrated from 001 with prefix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_trades (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    market_ticker VARCHAR(100) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('yes', 'no', 'YES', 'NO')),
    action VARCHAR(10) NOT NULL CHECK (action IN ('buy', 'sell', 'BUY', 'SELL')),
    contracts INTEGER NOT NULL,
    entry_price_cents INTEGER NOT NULL,
    fill_price_cents INTEGER,
    exit_price_cents INTEGER,
    pnl_cents INTEGER,
    order_id VARCHAR(100),
    exit_order_id VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'open', 'closed', 'cancelled', 'filled')),
    reasoning TEXT,
    exit_reason TEXT,
    strategy VARCHAR(50) NOT NULL,
    session_date DATE,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_deepstack_trades_created_at ON deepstack_trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deepstack_trades_status ON deepstack_trades(status);
CREATE INDEX IF NOT EXISTS idx_deepstack_trades_strategy ON deepstack_trades(strategy);
CREATE INDEX IF NOT EXISTS idx_deepstack_trades_session_date ON deepstack_trades(session_date);
CREATE INDEX IF NOT EXISTS idx_deepstack_trades_market_ticker ON deepstack_trades(market_ticker);

-- ============================================================================
-- DAILY SUMMARY (migrated with prefix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_daily_summary (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    gross_pnl_cents INTEGER DEFAULT 0,
    fees_cents INTEGER DEFAULT 0,
    net_pnl_cents INTEGER DEFAULT 0,
    largest_win_cents INTEGER DEFAULT 0,
    largest_loss_cents INTEGER DEFAULT 0,
    avg_winner_cents INTEGER DEFAULT 0,
    avg_loser_cents INTEGER DEFAULT 0,
    max_contracts INTEGER DEFAULT 0,
    starting_balance_cents INTEGER,
    ending_balance_cents INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deepstack_daily_summary_date ON deepstack_daily_summary(date DESC);

-- ============================================================================
-- OPPORTUNITIES (migrated with prefix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_opportunities (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    market_ticker VARCHAR(100) NOT NULL,
    strategy VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('YES', 'NO')),
    current_price_cents INTEGER NOT NULL,
    target_price_cents INTEGER NOT NULL,
    expected_profit_pct DECIMAL(10, 4),
    confidence DECIMAL(5, 4) CHECK (confidence >= 0 AND confidence <= 1),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'taken', 'expired', 'rejected')),
    reasoning TEXT,
    taken_at TIMESTAMPTZ,
    expired_at TIMESTAMPTZ,
    trade_id INTEGER REFERENCES deepstack_trades(id)
);

CREATE INDEX IF NOT EXISTS idx_deepstack_opportunities_created_at ON deepstack_opportunities(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deepstack_opportunities_status ON deepstack_opportunities(status);
CREATE INDEX IF NOT EXISTS idx_deepstack_opportunities_strategy ON deepstack_opportunities(strategy);

-- ============================================================================
-- DASHBOARD STATE (migrated with prefix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_dashboard_state (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    balance_cents INTEGER NOT NULL,
    daily_pnl_cents INTEGER DEFAULT 0,
    daily_pnl_percentage DECIMAL(10, 4) DEFAULT 0,
    total_positions INTEGER DEFAULT 0,
    available_balance_cents INTEGER NOT NULL,
    daily_loss_limit_cents INTEGER,
    daily_loss_used_cents INTEGER DEFAULT 0,
    max_position_size_cents INTEGER,
    kelly_fraction DECIMAL(5, 4),
    positions_at_risk INTEGER DEFAULT 0,
    risk_percentage DECIMAL(10, 4) DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_deepstack_dashboard_state_timestamp ON deepstack_dashboard_state(timestamp DESC);

-- ============================================================================
-- STRATEGY STATUS (migrated with prefix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_strategy_status (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    enabled BOOLEAN DEFAULT true,
    active_positions INTEGER DEFAULT 0,
    opportunities_found INTEGER DEFAULT 0,
    last_scan TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'inactive' CHECK (status IN ('active', 'inactive', 'scanning', 'error')),
    config JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- LOG ENTRIES (migrated with prefix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_log_entries (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    level VARCHAR(10) NOT NULL CHECK (level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR')),
    strategy VARCHAR(50),
    message TEXT NOT NULL,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_deepstack_log_entries_timestamp ON deepstack_log_entries(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_deepstack_log_entries_level ON deepstack_log_entries(level);
CREATE INDEX IF NOT EXISTS idx_deepstack_log_entries_strategy ON deepstack_log_entries(strategy);

-- ============================================================================
-- MARKET SNAPSHOTS (migrated with prefix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_market_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    market_ticker VARCHAR(100) NOT NULL,
    yes_price_cents INTEGER,
    no_price_cents INTEGER,
    volume INTEGER,
    open_interest INTEGER,
    last_trade_price_cents INTEGER,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_deepstack_market_snapshots_timestamp ON deepstack_market_snapshots(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_deepstack_market_snapshots_ticker ON deepstack_market_snapshots(market_ticker);

-- ============================================================================
-- PERFORMANCE METRICS (migrated with prefix)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_performance_metrics (
    id SERIAL PRIMARY KEY,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    period_type VARCHAR(20) NOT NULL CHECK (period_type IN ('hourly', 'daily', 'weekly', 'monthly')),
    strategy VARCHAR(50),
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    gross_pnl_cents INTEGER DEFAULT 0,
    fees_cents INTEGER DEFAULT 0,
    net_pnl_cents INTEGER DEFAULT 0,
    max_drawdown_cents INTEGER DEFAULT 0,
    sharpe_ratio DECIMAL(10, 4),
    win_rate DECIMAL(5, 4),
    avg_win_cents INTEGER DEFAULT 0,
    avg_loss_cents INTEGER DEFAULT 0,
    profit_factor DECIMAL(10, 4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(period_start, period_end, period_type, strategy)
);

CREATE INDEX IF NOT EXISTS idx_deepstack_performance_metrics_period ON deepstack_performance_metrics(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_deepstack_performance_metrics_strategy ON deepstack_performance_metrics(strategy);

-- ============================================================================
-- NEW: BOT COMMANDS (command queue — dashboard writes, bot reads)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_bot_commands (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    command TEXT NOT NULL,
    params JSONB DEFAULT '{}',
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'acknowledged', 'executed', 'failed')),
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    executed_at TIMESTAMPTZ,
    created_by TEXT DEFAULT 'dashboard'
);

CREATE INDEX IF NOT EXISTS idx_deepstack_bot_commands_pending
    ON deepstack_bot_commands (status, created_at ASC)
    WHERE status = 'pending';

-- ============================================================================
-- NEW: BOT CONFIG (singleton runtime config — both sides read/write)
-- ============================================================================

CREATE TABLE IF NOT EXISTS deepstack_bot_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    mode TEXT DEFAULT 'stopped' CHECK (mode IN ('running', 'stopped', 'paused', 'dry_run')),
    poll_interval_seconds INTEGER DEFAULT 60,
    max_position_size_cents INTEGER DEFAULT 5000,
    daily_loss_limit_cents INTEGER DEFAULT 10000,
    kelly_fraction DECIMAL(4,3) DEFAULT 0.500,
    strategies JSONB DEFAULT '[]',
    profile TEXT DEFAULT 'default',
    use_grok BOOLEAN DEFAULT false,
    last_heartbeat TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert singleton config row
INSERT INTO deepstack_bot_config DEFAULT VALUES
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- TRIGGERS (updated_at auto-update)
-- ============================================================================

CREATE OR REPLACE FUNCTION deepstack_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_deepstack_trades_updated_at ON deepstack_trades;
CREATE TRIGGER update_deepstack_trades_updated_at
    BEFORE UPDATE ON deepstack_trades
    FOR EACH ROW
    EXECUTE FUNCTION deepstack_update_updated_at();

DROP TRIGGER IF EXISTS update_deepstack_strategy_status_updated_at ON deepstack_strategy_status;
CREATE TRIGGER update_deepstack_strategy_status_updated_at
    BEFORE UPDATE ON deepstack_strategy_status
    FOR EACH ROW
    EXECUTE FUNCTION deepstack_update_updated_at();

DROP TRIGGER IF EXISTS update_deepstack_bot_config_updated_at ON deepstack_bot_config;
CREATE TRIGGER update_deepstack_bot_config_updated_at
    BEFORE UPDATE ON deepstack_bot_config
    FOR EACH ROW
    EXECUTE FUNCTION deepstack_update_updated_at();

-- ============================================================================
-- DEFAULT DATA
-- ============================================================================

INSERT INTO deepstack_strategy_status (name, enabled, status) VALUES
    ('mean_reversion', true, 'inactive'),
    ('combinatorial_arbitrage', true, 'inactive'),
    ('cross_platform_arbitrage', true, 'inactive'),
    ('momentum', true, 'inactive')
ON CONFLICT (name) DO NOTHING;
