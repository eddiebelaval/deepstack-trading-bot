-- Kalshi Trading Dashboard PostgreSQL Schema
-- Migration 001: Initial Schema

-- Trades table (primary trading data)
CREATE TABLE IF NOT EXISTS trades (
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

-- Indexes for trades
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
CREATE INDEX IF NOT EXISTS idx_trades_session_date ON trades(session_date);
CREATE INDEX IF NOT EXISTS idx_trades_market_ticker ON trades(market_ticker);

-- Daily summary table
CREATE TABLE IF NOT EXISTS daily_summary (
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

CREATE INDEX IF NOT EXISTS idx_daily_summary_date ON daily_summary(date DESC);

-- Opportunities table (detected trading opportunities)
CREATE TABLE IF NOT EXISTS opportunities (
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
    trade_id INTEGER REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_opportunities_created_at ON opportunities(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opportunities_strategy ON opportunities(strategy);

-- Dashboard state snapshots (for historical tracking)
CREATE TABLE IF NOT EXISTS dashboard_state (
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

CREATE INDEX IF NOT EXISTS idx_dashboard_state_timestamp ON dashboard_state(timestamp DESC);

-- Strategy status table
CREATE TABLE IF NOT EXISTS strategy_status (
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

-- Log entries table (for persistent feed)
CREATE TABLE IF NOT EXISTS log_entries (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    level VARCHAR(10) NOT NULL CHECK (level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR')),
    strategy VARCHAR(50),
    message TEXT NOT NULL,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_log_entries_timestamp ON log_entries(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_log_entries_level ON log_entries(level);
CREATE INDEX IF NOT EXISTS idx_log_entries_strategy ON log_entries(strategy);

-- Market data snapshots
CREATE TABLE IF NOT EXISTS market_snapshots (
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

CREATE INDEX IF NOT EXISTS idx_market_snapshots_timestamp ON market_snapshots(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_ticker ON market_snapshots(market_ticker);

-- Performance metrics (aggregated)
CREATE TABLE IF NOT EXISTS performance_metrics (
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

CREATE INDEX IF NOT EXISTS idx_performance_metrics_period ON performance_metrics(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_strategy ON performance_metrics(strategy);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
DROP TRIGGER IF EXISTS update_trades_updated_at ON trades;
CREATE TRIGGER update_trades_updated_at
    BEFORE UPDATE ON trades
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_strategy_status_updated_at ON strategy_status;
CREATE TRIGGER update_strategy_status_updated_at
    BEFORE UPDATE ON strategy_status
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Insert default strategies
INSERT INTO strategy_status (name, enabled, status) VALUES
    ('mean_reversion', true, 'inactive'),
    ('combinatorial_arbitrage', true, 'inactive'),
    ('cross_platform_arbitrage', true, 'inactive'),
    ('momentum', true, 'inactive')
ON CONFLICT (name) DO NOTHING;
