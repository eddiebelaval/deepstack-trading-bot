'use client';

import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import type { ChatMessage } from '@/lib/types';
import { shortTime, fullTime } from '@/lib/format';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function groupByDate(
  msgs: ChatMessage[],
): { date: string; messages: ChatMessage[] }[] {
  const groups: Record<string, ChatMessage[]> = {};
  for (const m of msgs) {
    const date = new Date(m.created_at).toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
    if (!groups[date]) groups[date] = [];
    groups[date].push(m);
  }
  return Object.entries(groups).map(([date, messages]) => ({ date, messages }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatHubPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'telegram' | 'dashboard'>(
    'all',
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const prevCountRef = useRef(0);

  // ---- Fetcher ----
  const fetchMessages = useCallback(async () => {
    try {
      const res = await fetch('/api/chat?limit=200');
      if (res.ok) {
        const d = await res.json();
        setMessages(d.messages || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  // ---- Initial load ----
  useEffect(() => {
    (async () => {
      await fetchMessages();
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Poll every 5s ----
  useEffect(() => {
    const interval = setInterval(fetchMessages, 5_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Auto-scroll on new messages ----
  useEffect(() => {
    if (messages.length > prevCountRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevCountRef.current = messages.length;
  }, [messages]);

  // ---- Send message ----
  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setSending(true);
    setInput('');
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      });
      if (res.ok) {
        await fetchMessages();
      }
    } catch {
      /* silent */
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  // ---- Keyboard: Enter to send, Shift+Enter for newline ----
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ---- Filtered messages (memoized) ----
  const filtered = useMemo(
    () => (filter === 'all' ? messages : messages.filter((m) => m.source === filter)),
    [messages, filter],
  );
  const grouped = useMemo(() => groupByDate(filtered), [filtered]);

  // ---- Stats (memoized) ----
  const { telegramCount, dashboardCount } = useMemo(() => {
    let tg = 0;
    let web = 0;
    for (const m of messages) {
      if (m.source === 'telegram') tg++;
      else web++;
    }
    return { telegramCount: tg, dashboardCount: web };
  }, [messages]);

  // ---- Loading state ----
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-lg terminal-glow-bright">
          CHAT HUB<span className="animate-cursor-blink">_</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="shrink-0 px-4 pt-4 pb-2 md:px-6 md:pt-6">
        <div className="flex items-center gap-3 mb-1">
          <div className="w-2 h-2 rounded-full bg-terminal-green animate-pulse" />
          <span className="text-[10px] text-terminal-green tracking-[0.2em] uppercase">
            Chat Hub
          </span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xl md:text-2xl font-bold terminal-glow tracking-wider">
              TALK TO DAE
            </div>
            <div className="text-[10px] text-terminal-dim mt-1">
              Unified conversation — Telegram + Dashboard | Polls every 5s
            </div>
          </div>

          {/* Channel filter */}
          <div className="flex items-center gap-1">
            {(
              [
                { key: 'all', label: 'ALL', count: messages.length },
                { key: 'telegram', label: 'TG', count: telegramCount },
                { key: 'dashboard', label: 'WEB', count: dashboardCount },
              ] as const
            ).map(({ key, label, count }) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`px-2 py-1 text-[9px] font-bold tracking-wider border rounded transition-all ${
                  filter === key
                    ? 'border-terminal-cyan bg-terminal-cyan/10 text-terminal-cyan'
                    : 'border-terminal-dim/20 text-terminal-dim hover:border-terminal-cyan/30'
                }`}
              >
                {label}
                <span className="ml-1 tabular-nums opacity-60">{count}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Messages area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 md:px-6 py-3 space-y-4"
      >
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-3">
            <div className="text-terminal-dim text-[10px] tracking-wider">
              NO MESSAGES YET
            </div>
            <div className="text-terminal-dim/50 text-[10px] max-w-sm">
              Send a message below or talk to Dae on Telegram. Both channels
              show up here.
            </div>
          </div>
        ) : (
          grouped.map(({ date, messages: dayMsgs }) => (
            <div key={date}>
              {/* Date separator */}
              <div className="flex items-center gap-3 my-3">
                <div className="flex-1 h-px bg-terminal-green/10" />
                <span className="text-[9px] text-terminal-dim tracking-wider">
                  {date}
                </span>
                <div className="flex-1 h-px bg-terminal-green/10" />
              </div>

              {/* Messages for this day */}
              <div className="space-y-2">
                {dayMsgs.map((msg) => {
                  const isUser = msg.role === 'user';
                  const isTelegram = msg.source === 'telegram';

                  return (
                    <div
                      key={msg.id}
                      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                    >
                      <div
                        className={`max-w-[85%] sm:max-w-[70%] lg:max-w-[60%] ${
                          isUser
                            ? 'bg-terminal-cyan/8 border border-terminal-cyan/20 rounded-lg rounded-br-sm'
                            : 'bg-terminal-bg-elevated border border-terminal-green/15 rounded-lg rounded-bl-sm'
                        } px-3 py-2`}
                      >
                        {/* Header: source badge + timestamp */}
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={`text-[9px] font-bold tracking-wider ${
                              isUser
                                ? 'text-terminal-cyan'
                                : 'text-terminal-green'
                            }`}
                          >
                            {isUser ? 'EDDIE' : 'DAE'}
                          </span>
                          <span
                            className={`text-[9px] px-1 py-px rounded border ${
                              isTelegram
                                ? 'text-terminal-amber/70 border-terminal-amber/20 bg-terminal-amber/5'
                                : 'text-terminal-cyan/70 border-terminal-cyan/20 bg-terminal-cyan/5'
                            }`}
                          >
                            {isTelegram ? 'TG' : 'WEB'}
                          </span>
                          <span
                            className="text-[9px] text-terminal-dim/50 tabular-nums ml-auto"
                            title={fullTime(msg.created_at)}
                          >
                            {shortTime(msg.created_at)}
                          </span>
                        </div>

                        {/* Content */}
                        <div
                          className={`text-[11px] leading-relaxed whitespace-pre-wrap break-words ${
                            isUser
                              ? 'text-terminal-cyan/90'
                              : 'text-terminal-green-dim'
                          }`}
                        >
                          {msg.content}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Input area */}
      <div className="shrink-0 border-t border-terminal-green/15 px-4 md:px-6 py-3 bg-terminal-bg-elevated/50">
        <div className="flex items-end gap-2 max-w-[1600px] mx-auto">
          {/* Source indicator */}
          <div className="shrink-0 pb-2">
            <span className="text-[9px] text-terminal-cyan/50 border border-terminal-cyan/20 rounded px-1.5 py-0.5">
              WEB
            </span>
          </div>

          {/* Text input */}
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Talk to Dae..."
              rows={1}
              className="w-full px-3 py-2 bg-terminal-bg border border-terminal-green/20 rounded text-[11px] text-terminal-green font-mono
                focus:outline-none focus:border-terminal-green/40 focus:shadow-[0_0_8px_rgba(0,255,65,0.08)]
                placeholder:text-terminal-dim/30 resize-none leading-relaxed"
              style={{ minHeight: 38, maxHeight: 120 }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = 'auto';
                target.style.height =
                  Math.min(target.scrollHeight, 120) + 'px';
              }}
            />
          </div>

          {/* Send button */}
          <button
            onClick={handleSend}
            disabled={!input.trim() || sending}
            className={`shrink-0 px-4 py-2 text-[10px] font-bold tracking-wider border rounded transition-all ${
              !input.trim() || sending
                ? 'border-terminal-dim/20 text-terminal-dim/30 cursor-not-allowed'
                : 'border-terminal-green text-terminal-green hover:bg-terminal-green/10 hover:shadow-[0_0_10px_rgba(0,255,65,0.15)]'
            }`}
          >
            {sending ? 'SENDING...' : 'SEND'}
          </button>
        </div>
        <div className="text-[9px] text-terminal-dim/30 mt-1.5 ml-10">
          Enter to send | Shift+Enter for newline | Dae responds via bot cycle
          or Telegram
        </div>
      </div>
    </div>
  );
}
