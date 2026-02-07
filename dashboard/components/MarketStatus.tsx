'use client';

import { useEffect, useState } from 'react';
import { getMarketStatus, type MarketState } from '@/lib/market-hours';

const STATE_STYLES: Record<MarketState, { dot: string; text: string; glow: string }> = {
  open: {
    dot: 'bg-terminal-green animate-pulse shadow-[0_0_8px_#00FF41]',
    text: 'text-terminal-green-bright font-bold',
    glow: 'border-terminal-green/30',
  },
  pre_market: {
    dot: 'bg-terminal-amber animate-pulse shadow-[0_0_6px_#FFB800]',
    text: 'text-terminal-amber',
    glow: 'border-terminal-amber/20',
  },
  after_hours: {
    dot: 'bg-terminal-amber shadow-[0_0_4px_#FFB800]',
    text: 'text-terminal-amber',
    glow: 'border-terminal-amber/20',
  },
  closed: {
    dot: 'bg-[#4a4a65]',
    text: 'text-terminal-dim',
    glow: 'border-terminal-dim/20',
  },
};

export default function MarketStatus({ compact = false }: { compact?: boolean }) {
  const [status, setStatus] = useState(() => getMarketStatus());

  useEffect(() => {
    const interval = setInterval(() => setStatus(getMarketStatus()), 30_000);
    return () => clearInterval(interval);
  }, []);

  const style = STATE_STYLES[status.state];

  if (compact) {
    return (
      <div className="flex items-center gap-1.5">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${style.dot}`} />
        <span className={`text-[10px] uppercase tracking-wider ${style.text}`}>
          {status.state === 'open' ? 'MKT' : status.label}
        </span>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-2 px-2.5 py-1 border rounded ${style.glow}`}>
      <span className={`inline-block w-2 h-2 rounded-full ${style.dot}`} />
      <div className="flex flex-col">
        <span className={`text-[10px] uppercase tracking-wider leading-tight ${style.text}`}>
          {status.label}
        </span>
        <span className="text-[9px] text-terminal-dim leading-tight">
          {status.nextChange}
        </span>
      </div>
    </div>
  );
}
