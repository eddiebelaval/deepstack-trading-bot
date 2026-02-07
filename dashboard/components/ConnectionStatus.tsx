'use client';

import { useEffect, useState } from 'react';

type ConnectionState = 'connected' | 'degraded' | 'disconnected';

interface ConnectionStatusProps {
  className?: string;
}

const STATUS_CONFIG = {
  connected: {
    color: 'text-terminal-green',
    dotColor: 'bg-terminal-green',
    shadow: 'shadow-[0_0_4px_#00FF41]',
    label: 'CONNECTED',
  },
  degraded: {
    color: 'text-terminal-amber',
    dotColor: 'bg-terminal-amber',
    shadow: 'shadow-[0_0_4px_#FFBF00]',
    label: 'SLOW',
  },
  disconnected: {
    color: 'text-terminal-red',
    dotColor: 'bg-terminal-red',
    shadow: 'shadow-[0_0_4px_#FF0000]',
    label: 'OFFLINE',
  },
} as const;

const LATENCY_THRESHOLD_MS = 500;
const CHECK_INTERVAL_MS = 10000;

export default function ConnectionStatus({ className = '' }: ConnectionStatusProps): JSX.Element {
  const [status, setStatus] = useState<ConnectionState>('connected');
  const [latency, setLatency] = useState<number>(0);

  useEffect(() => {
    async function checkConnection(): Promise<void> {
      const start = Date.now();
      try {
        const response = await fetch('/api/status', { method: 'HEAD' });
        const elapsed = Date.now() - start;
        setLatency(elapsed);

        if (response.ok) {
          setStatus(elapsed > LATENCY_THRESHOLD_MS ? 'degraded' : 'connected');
        } else {
          setStatus('disconnected');
        }
      } catch {
        setStatus('disconnected');
        setLatency(0);
      }
    }

    checkConnection();
    const interval = setInterval(checkConnection, CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const config = STATUS_CONFIG[status];

  return (
    <div className={`flex items-center gap-2 text-xs ${className}`}>
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${config.dotColor} ${config.shadow}`} />
      <span className={config.color}>{config.label}</span>
      {status !== 'disconnected' && (
        <span className="text-terminal-dim">{latency}ms</span>
      )}
    </div>
  );
}
