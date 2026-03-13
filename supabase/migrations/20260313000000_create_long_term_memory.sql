-- Long-term memory for Dae — persistent facts that survive across restarts.
-- Read by the bot at startup and heartbeat cycles.

CREATE TABLE IF NOT EXISTS deepstack_long_term_memory (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast key lookups
CREATE INDEX IF NOT EXISTS idx_ltm_key ON deepstack_long_term_memory (key);
CREATE INDEX IF NOT EXISTS idx_ltm_category ON deepstack_long_term_memory (category);

-- RLS: service role can read/write, anon can read
ALTER TABLE deepstack_long_term_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on long_term_memory"
    ON deepstack_long_term_memory
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Seed the initial long-term memory entries
INSERT INTO deepstack_long_term_memory (key, value, category) VALUES
    ('owner', 'Eddie Belaval, founder of id8Labs LLC. Building generational wealth through disciplined algorithmic trading.', 'identity'),
    ('mission', 'Turn $159.64 into generational wealth through compounding small edges over thousands of trades. Think in centuries, not quarters.', 'identity'),
    ('phase', 'SEED ($0-$500). Proven edges only. 70% reserve. Capital preservation above growth.', 'capital'),
    ('primary_strategy', 'calibration_edge — exploits favorite-longshot bias on Kalshi prediction markets. 87% win rate on 145 paper trades. Graduated to live 2026-03-11.', 'strategy'),
    ('risk_philosophy', 'Oak Tree Principles: capital preservation first, 70% reserve discipline, fractional Kelly (0.02), circuit breakers sacred, never override daily loss limit ($5).', 'risk'),
    ('plan_reference', '90-day wealth engine plan in mind/drives/90_day_wealth_engine.md. Phase 1: Diagnostics (Mar 13-27). Phase 2: Optimization (Mar 28 - Apr 27). Phase 3: Compounding (Apr 28 - Jun 11).', 'planning'),
    ('oak_tree_report', 'Weekly Oak Tree Report every Sunday. First report: March 16, 2026. Covers balance vs target, per-strategy P&L, regime status, lessons learned.', 'reporting')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
