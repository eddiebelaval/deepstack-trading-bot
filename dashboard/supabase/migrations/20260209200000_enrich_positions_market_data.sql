-- Add market enrichment columns to deepstack_positions
-- These fields come from the Kalshi GET /markets/{ticker} API response

ALTER TABLE deepstack_positions
  ADD COLUMN IF NOT EXISTS volume_24h integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS open_interest integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS previous_price integer,
  ADD COLUMN IF NOT EXISTS price_change_cents integer GENERATED ALWAYS AS (
    CASE WHEN previous_price IS NOT NULL AND current_price IS NOT NULL
         THEN current_price - previous_price
         ELSE NULL
    END
  ) STORED;
