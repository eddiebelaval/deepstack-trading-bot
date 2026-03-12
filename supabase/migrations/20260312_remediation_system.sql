-- Tier 2 Remediation System
-- Adds sensory check columns to health_status and creates remediation queue table.

-- Add sensory check columns to existing health_status table
ALTER TABLE deepstack_health_status
    ADD COLUMN IF NOT EXISTS sensory_status TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS sensory_report JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS consecutive_critical INTEGER NOT NULL DEFAULT 0;

-- Remediation queue: sensory_check.py writes pending requests, remediate.py consumes them
CREATE TABLE IF NOT EXISTS deepstack_remediation_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consecutive_critical INTEGER NOT NULL DEFAULT 0,
    failures JSONB DEFAULT '[]'::jsonb,
    full_report JSONB DEFAULT '{}'::jsonb,
    prompt TEXT NOT NULL DEFAULT '',
    result TEXT DEFAULT '',
    completed_at TIMESTAMPTZ
);

-- Index for polling: remediate.py queries status=pending ordered by created_at
CREATE INDEX IF NOT EXISTS idx_remediation_queue_status
    ON deepstack_remediation_queue (status, created_at DESC);

-- RLS: service role only
ALTER TABLE deepstack_remediation_queue ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'deepstack_remediation_queue'
        AND policyname = 'service_role_remediation_queue'
    ) THEN
        CREATE POLICY "service_role_remediation_queue" ON deepstack_remediation_queue
            FOR ALL USING (auth.role() = 'service_role');
    END IF;
END $$;
