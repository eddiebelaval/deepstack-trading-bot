-- Performance indexes for Kalshi Trading Dashboard
-- Run with: psql -d kalshi_trading -f add_indexes.sql

-- Trades table indexes
-- Composite index for common date + status queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_session_date_status
ON trades(session_date, status);

-- Composite index for strategy analysis
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_strategy_status
ON trades(strategy, status);

-- Index for finding open positions quickly
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_status_created
ON trades(status, created_at DESC)
WHERE status = 'open';

-- Partial index for closed trades P&L analysis
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_closed_pnl
ON trades(session_date, pnl_cents)
WHERE status = 'closed';

-- Index for market ticker lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_market_ticker
ON trades(market_ticker);

-- Opportunities table indexes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_opportunities_status_created
ON opportunities(status, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_opportunities_strategy_status
ON opportunities(strategy, status);

-- Daily summary indexes (usually small table, but helps)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_daily_summary_date
ON daily_summary(date DESC);

-- Market snapshots indexes (can grow large)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_market_snapshots_ticker_time
ON market_snapshots(market_ticker, timestamp DESC);

-- Performance metrics indexes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_performance_period_type
ON performance_metrics(period_type, period_start DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_performance_strategy_period
ON performance_metrics(strategy, period_type, period_start DESC);

-- Log entries (for debugging, frequently queried by time)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_log_entries_timestamp
ON log_entries(timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_log_entries_level_timestamp
ON log_entries(level, timestamp DESC);

-- Dashboard state (usually just latest is needed)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dashboard_state_timestamp
ON dashboard_state(timestamp DESC);

-- Strategy status (small table, but index helps)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_strategy_status_enabled
ON strategy_status(enabled, name);

-- Analyze tables after adding indexes
ANALYZE trades;
ANALYZE opportunities;
ANALYZE daily_summary;
ANALYZE market_snapshots;
ANALYZE performance_metrics;
ANALYZE log_entries;
ANALYZE dashboard_state;
ANALYZE strategy_status;
