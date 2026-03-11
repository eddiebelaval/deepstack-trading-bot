-- Preserve which market domain produced each regime snapshot.
-- Existing rows should continue to behave like prediction-market records.

ALTER TABLE IF EXISTS deepstack_regime_history
ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'prediction_market';

UPDATE deepstack_regime_history
SET source = 'prediction_market'
WHERE source IS NULL;

CREATE INDEX IF NOT EXISTS idx_regime_history_source_timestamp
ON deepstack_regime_history (source, timestamp DESC);
