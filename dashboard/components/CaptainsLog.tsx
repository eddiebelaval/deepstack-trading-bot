'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { CaptainsLogEntry } from '@/lib/types';

export default function CaptainsLog() {
  const [entries, setEntries] = useState<CaptainsLogEntry[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [chatExpanded, setChatExpanded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const modalScrollRef = useRef<HTMLDivElement>(null);
  const lastTimestampRef = useRef<string | null>(null);

  // Scroll to bottom when new entries arrive (if user is near bottom)
  const scrollToBottom = useCallback(() => {
    if (isNearBottom && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [isNearBottom]);

  // Track scroll position
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const threshold = 100;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
    setIsNearBottom(atBottom);
  }, []);

  // Initial fetch
  useEffect(() => {
    const fetchInitial = async () => {
      try {
        const res = await fetch('/api/captains-log?limit=50');
        if (res.ok) {
          const data = await res.json();
          const fetched: CaptainsLogEntry[] = data.entries || [];
          setEntries(fetched);
          if (fetched.length > 0) {
            lastTimestampRef.current = fetched[fetched.length - 1].created_at;
          }
        }
      } catch (err) {
        console.error('Failed to fetch log:', err);
      }
    };
    fetchInitial();
  }, []);

  // Poll for new entries every 2s (incremental)
  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const afterParam = lastTimestampRef.current
          ? `&after=${encodeURIComponent(lastTimestampRef.current)}`
          : '';
        const res = await fetch(`/api/captains-log?limit=50${afterParam}`);
        if (res.ok) {
          const data = await res.json();
          const newEntries: CaptainsLogEntry[] = data.entries || [];
          if (newEntries.length > 0) {
            setEntries(prev => {
              const existingIds = new Set(prev.map(e => e.id));
              const deduped = newEntries.filter(e => !existingIds.has(e.id));
              if (deduped.length === 0) return prev;
              const merged = [...prev, ...deduped];
              return merged.length > 500 ? merged.slice(-500) : merged;
            });
            lastTimestampRef.current = newEntries[newEntries.length - 1].created_at;
          }
        }
      } catch {
        // Polling failure is non-critical
      }
    }, 2000);

    return () => clearInterval(poll);
  }, []);

  // Auto-scroll on new entries
  useEffect(() => {
    scrollToBottom();
  }, [entries, scrollToBottom]);

  // Scroll modal to bottom when opened or new entries arrive
  useEffect(() => {
    if (chatExpanded && modalScrollRef.current) {
      modalScrollRef.current.scrollTop = modalScrollRef.current.scrollHeight;
    }
  }, [chatExpanded, entries]);

  // Send user message
  const handleSend = async () => {
    const msg = input.trim();
    if (!msg || sending) return;

    setSending(true);
    setInput('');

    try {
      const res = await fetch('/api/captains-log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.entry) {
          setEntries(prev => [...prev, data.entry]);
          lastTimestampRef.current = data.entry.created_at;
          setIsNearBottom(true);
        }
      }
    } catch (err) {
      console.error('Failed to send message:', err);
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const priorityColor = (priority: string) => {
    switch (priority) {
      case 'critical': return 'text-terminal-red';
      case 'significant': return 'text-terminal-amber';
      default: return 'text-terminal-green';
    }
  };

  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '--:--';
    }
  };

  const renderEntry = (entry: CaptainsLogEntry) => (
    <div
      key={entry.id}
      className={`flex flex-col ${entry.role === 'user' ? 'items-end' : 'items-start'}`}
    >
      <div
        className={`max-w-[90%] px-2.5 py-1.5 rounded text-xs font-mono leading-relaxed ${
          entry.role === 'user'
            ? 'bg-terminal-green/10 border border-terminal-green/30 text-terminal-green'
            : `bg-terminal-bg-elevated border border-terminal-green/20 ${priorityColor(entry.priority)}`
        }`}
      >
        {entry.role === 'bot' && entry.event_type && (
          <span className="inline-block text-[9px] text-terminal-cyan font-bold tracking-wider uppercase mr-1.5">
            [{entry.event_type}]
          </span>
        )}
        {entry.role === 'bot' && entry.strategy && (
          <span className="inline-block text-[9px] text-terminal-amber-dim tracking-wider mr-1.5">
            {entry.strategy}
          </span>
        )}
        <span className="whitespace-pre-wrap">{entry.content}</span>
      </div>
      <span className="text-[9px] text-terminal-cyan-dim mt-0.5 px-1">
        {formatTime(entry.created_at)}
      </span>
    </div>
  );

  return (
    <div className="flex flex-col h-full border border-terminal-green/30 rounded bg-terminal-bg">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-terminal-green/30 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-wider terminal-glow">COMMS</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-terminal-green-dim tracking-wider">LIVE</span>
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-terminal-green animate-live-pulse" />
        </div>
      </div>

      {/* Narration feed — dominant area */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-3 py-2 space-y-2 min-h-0"
      >
        {entries.length === 0 && (
          <div className="text-terminal-green-dim text-xs text-center py-8">
            Waiting for bot narration...
          </div>
        )}

        {entries.map(renderEntry)}

        <div ref={messagesEndRef} />
      </div>

      {/* Scroll indicator */}
      {!isNearBottom && entries.length > 0 && (
        <button
          onClick={() => {
            setIsNearBottom(true);
            messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
          }}
          className="mx-3 mb-1 px-2 py-0.5 text-[10px] text-terminal-cyan bg-terminal-bg-elevated border border-terminal-cyan/30 rounded text-center hover:bg-terminal-cyan/10 transition-colors"
        >
          NEW MESSAGES
        </button>
      )}

      {/* Compact chat input — small bar, expand for full chat */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-t border-terminal-green/20 shrink-0">
        <span className="text-terminal-green/40 text-[10px]">&gt;</span>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value.slice(0, 500))}
          onKeyDown={handleKeyDown}
          placeholder="Message..."
          disabled={sending}
          className="flex-1 bg-transparent text-[10px] font-mono text-terminal-green placeholder:text-terminal-green-dim/30 focus:outline-none disabled:opacity-50"
        />
        <button
          onClick={() => setChatExpanded(true)}
          className="px-1 text-[10px] text-terminal-dim hover:text-terminal-green transition-colors"
          title="Expand chat"
        >
          [+]
        </button>
      </div>

      {/* Glass chat modal */}
      {chatExpanded && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop — frosted glass */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-md"
            onClick={() => setChatExpanded(false)}
          />
          {/* Modal panel */}
          <div
            className="relative w-full max-w-xl mx-4 flex flex-col border border-terminal-green/30 rounded-lg bg-terminal-bg/95 backdrop-blur-sm"
            style={{ maxHeight: '70vh' }}
          >
            {/* Modal header */}
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-terminal-green/30 shrink-0">
              <span className="text-xs font-bold tracking-wider terminal-glow">MESSAGE DEEPSTACK</span>
              <button
                onClick={() => setChatExpanded(false)}
                className="text-terminal-dim hover:text-terminal-green text-xs transition-colors"
              >
                [X]
              </button>
            </div>
            {/* Modal messages */}
            <div
              ref={modalScrollRef}
              className="flex-1 overflow-y-auto px-4 py-3 space-y-2 min-h-0"
            >
              {entries.map(renderEntry)}
            </div>
            {/* Modal input */}
            <div className="flex items-center gap-2 px-4 py-3 border-t border-terminal-green/30 shrink-0">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value.slice(0, 500))}
                onKeyDown={handleKeyDown}
                placeholder="Message DeepStack..."
                disabled={sending}
                autoFocus
                className="flex-1 bg-terminal-bg-elevated border border-terminal-green/30 rounded px-3 py-2 text-xs font-mono text-terminal-green placeholder:text-terminal-green-dim/40 focus:outline-none focus:border-terminal-green/60 disabled:opacity-50"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || sending}
                className="px-4 py-2 text-[10px] font-bold tracking-wider bg-terminal-green/10 border border-terminal-green/40 text-terminal-green rounded hover:bg-terminal-green/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                SEND
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
