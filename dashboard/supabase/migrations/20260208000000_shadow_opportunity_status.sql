-- Add "shadow" to the deepstack_opportunities status CHECK constraint.
-- Shadow opportunities are logged by disabled strategies for tracking
-- "lost opportunities" — what would have been traded if the strategy were enabled.

ALTER TABLE deepstack_opportunities
    DROP CONSTRAINT IF EXISTS deepstack_opportunities_status_check;

ALTER TABLE deepstack_opportunities
    ADD CONSTRAINT deepstack_opportunities_status_check
    CHECK (status IN ('active', 'taken', 'expired', 'rejected', 'shadow'));
