'use client';

import { useEffect, useState, useRef } from 'react';
import { LogEntry } from '@/lib/types';

export default function LiveFeed() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [feedError, setFeedError] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Fetch logs initially
    fetchLogs();

    // Poll for new logs every 2 seconds
    const interval = setInterval(fetchLogs, 2000);

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    // Auto-scroll to bottom when new logs arrive
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const fetchLogs = async () => {
    try {
      const response = await fetch('/api/feed');
      if (response.ok) {
        const data = await response.json();
        setLogs(data.logs);
        setFeedError(false);
      } else {
        setFeedError(true);
      }
    } catch (error) {
      console.error('Failed to fetch logs:', error);
      setFeedError(true);
    }
  };

  const getLevelSymbol = (level: string) => {
    switch (level) {
      case 'INFO':
        return '[i]';
      case 'WARNING':
        return '[!]';
      case 'ERROR':
        return '[X]';
      case 'DEBUG':
        return '[d]';
      default:
        return '[ ]';
    }
  };

  const getLevelClass = (level: string) => {
    switch (level) {
      case 'ERROR':
        return 'text-terminal-red-bright';
      case 'WARNING':
        return 'text-terminal-amber amber-glow';
      case 'DEBUG':
        return 'text-terminal-cyan-dim';
      default:
        return 'text-terminal-green';
    }
  };

  return (
    <div className="panel p-4 h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-terminal-green pb-2 mb-3 transition-all duration-300">
        <div className="flex items-center justify-between">
          <div className="text-lg font-bold terminal-glow tracking-wide transition-all duration-300 hover:terminal-glow-bright">
            LIVE FEED
          </div>
          <div className={`text-xs ${feedError ? 'text-terminal-red' : 'text-terminal-dim'}`}>
            {feedError ? 'DISCONNECTED' : <>STREAMING <span className="cursor animate-cursor-blink">_</span></>}
          </div>
        </div>
      </div>

      {/* Log output */}
      <div
        ref={scrollRef}
        className="flex-grow overflow-y-auto font-mono text-sm leading-relaxed space-y-2"
        style={{ maxHeight: '400px' }}
      >
        {logs.length === 0 ? (
          <div className="text-terminal-dim animate-fade-in">
            WAITING FOR DATA<span className="cursor animate-cursor-blink">_</span>
          </div>
        ) : (
          logs.map((log, idx) => (
            <div key={idx} className="flex gap-3 animate-fade-in hover:bg-terminal-green hover:bg-opacity-5 px-2 -mx-2 py-1 transition-all duration-200 rounded">
              <span className="text-terminal-cyan-dim shrink-0">
                {log.timestamp}
              </span>
              <span className={`shrink-0 ${getLevelClass(log.level)}`}>
                {getLevelSymbol(log.level)}
              </span>
              {log.strategy && (
                <span className="text-terminal-amber shrink-0">
                  [{log.strategy}]
                </span>
              )}
              <span className="text-terminal-green break-all">
                {log.message}
              </span>
            </div>
          ))
        )}
        <div className="flex gap-3">
          <span className="text-terminal-cyan-dim">
            {new Date().toTimeString().split(' ')[0]}
          </span>
          <span className="cursor animate-cursor-blink">_</span>
        </div>
      </div>
    </div>
  );
}
