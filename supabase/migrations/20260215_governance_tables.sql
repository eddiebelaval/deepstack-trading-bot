-- Market Governance Tables
-- Stores regime history, strategy-regime fitness, and governance decisions
-- for the MarketGovernor self-governance brain.

-- Regime history: one row per governance cycle
CREATE TABLE IF NOT EXISTS deepstack_regime_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    regime TEXT NOT NULL,
    confidence REAL NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    volatility REAL,
    trend_strength REAL,
    mean_reversion_score REAL,
    volume_ratio REAL,
    num_markets_sampled INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Strategy-regime fitness: maps (strategy, regime) to performance
CREATE TABLE IF NOT EXISTS deepstack_strategy_regime_fitness (
    strategy_name TEXT NOT NULL,
    regime TEXT NOT NULL,
    fitness_score REAL DEFAULT 0.5,
    trade_count INTEGER DEFAULT 0,
    total_pnl_cents REAL DEFAULT 0.0,
    last_updated TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (strategy_name, regime)
);

-- Governance decisions: audit trail of all governor actions
CREATE TABLE IF NOT EXISTS deepstack_governance_decisions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    regime TEXT NOT NULL,
    regime_confidence REAL,
    action TEXT NOT NULL,
    strategy_name TEXT,
    reason TEXT,
    mode TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS: all governance tables use service role only (bot writes, dashboard reads)
ALTER TABLE deepstack_regime_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_strategy_regime_fitness ENABLE ROW LEVEL SECURITY;
ALTER TABLE deepstack_governance_decisions ENABLE ROW LEVEL SECURITY;

-- Service role can do everything
CREATE POLICY "service_role_regime_history" ON deepstack_regime_history
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_strategy_regime_fitness" ON deepstack_strategy_regime_fitness
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_governance_decisions" ON deepstack_governance_decisions
    FOR ALL USING (auth.role() = 'service_role');

-- Indexes for dashboard queries
CREATE INDEX idx_regime_history_timestamp ON deepstack_regime_history (timestamp DESC);
CREATE INDEX idx_governance_decisions_timestamp ON deepstack_governance_decisions (timestamp DESC);
CREATE INDEX idx_governance_decisions_strategy ON deepstack_governance_decisions (strategy_name);
