-- Backtest results table for hybrid graduation
-- Stores per-strategy aggregate metrics from backtest/arena runs
-- Used by graduation API to blend backtest confidence with paper trading data

CREATE TABLE IF NOT EXISTS deepstack_backtest_results (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy        TEXT NOT NULL,
    gate            TEXT NOT NULL,  -- KALSHI, STOCKS, FUTURES, OPTIONS

    -- Core metrics (from BacktestResult)
    total_trades    INT NOT NULL DEFAULT 0,
    win_rate        DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_drawdown_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    sharpe_ratio    DOUBLE PRECISION NOT NULL DEFAULT 0,
    profit_factor   DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_pnl_cents   DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_pnl_cents INT NOT NULL DEFAULT 0,

    -- Arena composite score (0-100 percentile-weighted)
    composite_score DOUBLE PRECISION NOT NULL DEFAULT 0,

    -- Run metadata
    data_source     TEXT NOT NULL DEFAULT 'synthetic',  -- synthetic, csv, sqlite, kalshi_api, seas
    time_window     TEXT,                                -- e.g. "2025-06 to 2026-02"
    run_id          TEXT,                                -- links to TournamentResult.tournament_id
    timesteps       INT NOT NULL DEFAULT 0,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for graduation API: latest results per strategy per gate
CREATE INDEX idx_backtest_results_gate_strategy
    ON deepstack_backtest_results (gate, strategy, created_at DESC);

-- Index for querying latest run per gate
CREATE INDEX idx_backtest_results_gate_latest
    ON deepstack_backtest_results (gate, created_at DESC);

-- RLS: service role only (bot writes, dashboard reads via API route)
ALTER TABLE deepstack_backtest_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access"
    ON deepstack_backtest_results
    FOR ALL
    USING (true)
    WITH CHECK (true);
