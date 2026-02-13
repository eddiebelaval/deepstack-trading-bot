-- Health Monitor Status Table
-- Stores periodic health snapshots from the self-healing health monitor.
-- Single row (upserted by ID) — always shows the latest health state.

CREATE TABLE IF NOT EXISTS deepstack_health_status (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- Singleton row
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    overall_status TEXT NOT NULL DEFAULT 'unknown',  -- healthy, degraded, critical
    uptime_seconds INTEGER DEFAULT 0,
    last_trade_time TIMESTAMPTZ,
    cycles_since_last_trade INTEGER DEFAULT 0,
    cycles_with_zero_opportunities INTEGER DEFAULT 0,
    api_status TEXT DEFAULT 'unknown',
    api_latency_ms REAL DEFAULT 0.0,
    market_data_status TEXT DEFAULT 'unknown',  -- fresh, stale, unavailable
    markets_available JSONB DEFAULT '{}',
    strategy_health JSONB DEFAULT '{}',
    db_wal_size_mb REAL DEFAULT 0.0,
    log_size_mb REAL DEFAULT 0.0,
    governor_regime TEXT DEFAULT 'unknown',
    governor_confidence REAL DEFAULT 0.0,
    errors_last_hour JSONB DEFAULT '[]',
    self_heal_actions JSONB DEFAULT '[]',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Insert the singleton row
INSERT INTO deepstack_health_status (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

-- RLS: service role only (bot writes, dashboard reads via service key)
ALTER TABLE deepstack_health_status ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_health_status" ON deepstack_health_status
    FOR ALL USING (auth.role() = 'service_role');

-- Auto-update timestamp
CREATE OR REPLACE FUNCTION update_health_status_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER health_status_updated_at
    BEFORE UPDATE ON deepstack_health_status
    FOR EACH ROW EXECUTE FUNCTION update_health_status_timestamp();
