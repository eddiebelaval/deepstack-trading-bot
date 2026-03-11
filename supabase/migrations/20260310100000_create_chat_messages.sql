-- Unified Chat Hub: stores messages from both Telegram and Dashboard
-- so the dashboard can display a unified conversation timeline with Dae.

CREATE TABLE IF NOT EXISTS deepstack_chat_messages (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at  timestamptz DEFAULT now(),
  source      text NOT NULL CHECK (source IN ('telegram', 'dashboard')),
  role        text NOT NULL CHECK (role IN ('user', 'bot')),
  content     text NOT NULL,
  session_id  text,
  metadata    jsonb DEFAULT '{}'::jsonb
);

-- Indexes for efficient polling (dashboard polls newest messages)
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at
  ON deepstack_chat_messages (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_source
  ON deepstack_chat_messages (source);

-- RLS: service_role only (bot + dashboard API routes use service key)
ALTER TABLE deepstack_chat_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON deepstack_chat_messages
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');
