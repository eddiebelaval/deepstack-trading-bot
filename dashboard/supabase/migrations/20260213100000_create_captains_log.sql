-- Captain's Log: streaming AI narration for DeepStack
-- Bot writes narration entries; dashboard polls and displays as chat.

CREATE TABLE deepstack_captains_log (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at  timestamptz DEFAULT now(),
  role        text NOT NULL CHECK (role IN ('bot', 'user')),
  content     text NOT NULL,
  event_type  text,
  priority    text DEFAULT 'routine' CHECK (priority IN ('critical', 'significant', 'routine')),
  strategy    text,
  regime      text,
  model_used  text,
  tokens_used int,
  metadata    jsonb DEFAULT '{}'::jsonb
);
-- Primary query: newest entries first (dashboard polling)
CREATE INDEX idx_captains_log_created ON deepstack_captains_log (created_at DESC);
-- Bot-only entries for context window building
CREATE INDEX idx_captains_log_bot ON deepstack_captains_log (created_at DESC) WHERE role = 'bot';
-- RLS: service_role only (bot writes, dashboard reads via service key)
ALTER TABLE deepstack_captains_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all" ON deepstack_captains_log
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
