'use client';

import { useEffect, useState } from 'react';

export default function Header() {
  const [currentTime, setCurrentTime] = useState<string>('');
  const isLive = true; // Always live in this version

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      const timeStr = now.toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
      const dateStr = now.toLocaleDateString('en-US', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
      });
      setCurrentTime(`${dateStr} ${timeStr}`);
    };

    updateTime();
    const interval = setInterval(updateTime, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="mb-4 flex items-center justify-between gap-4">
      {/* Title Box */}
      <div className="inline-block border border-terminal-green px-4 md:px-6 py-2 md:py-3 card-hover scan-hover transition-all duration-300">
        <div className="text-lg md:text-2xl font-bold terminal-glow-bright tracking-widest animate-phosphor-pulse text-center">
          DEEPSTACK TRADER v2.0
        </div>
      </div>

      {/* Status and Time */}
      <div className="flex items-center gap-4 md:gap-6 text-xs md:text-sm">
        <div className="flex items-center gap-2">
          <span className={`inline-block w-2 h-2 rounded-full ${
            isLive
              ? 'bg-terminal-green animate-pulse shadow-[0_0_8px_#00FF41]'
              : 'bg-terminal-red'
          }`} />
          <span className={isLive ? 'text-terminal-green-bright font-bold' : 'text-terminal-red'}>
            {isLive ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
        <div className="tabular-nums text-terminal-cyan transition-all duration-300">
          {currentTime}
        </div>
      </div>
    </div>
  );
}
