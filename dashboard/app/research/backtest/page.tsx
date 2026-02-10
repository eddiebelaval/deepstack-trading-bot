'use client';

import { useState, useEffect, useCallback } from 'react';
import type { BacktestResult, BacktestHistoryEntry } from '@/lib/research-types';
import BacktestForm from '@/components/research/BacktestForm';
import BacktestReport from '@/components/research/BacktestReport';

const HISTORY_KEY = 'deepstack_backtest_history';
const MAX_HISTORY = 5;

function loadHistory(): BacktestHistoryEntry[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveHistory(entry: BacktestHistoryEntry) {
  const history = loadHistory();
  history.unshift(entry);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
}

export default function BacktestPage() {
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<BacktestHistoryEntry[]>([]);

  useEffect(() => {
    setHistory(loadHistory());
  }, []);

  const handleSubmit = useCallback(async (url: string) => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch('/api/research/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        setError(data.error || `Request failed (${res.status})`);
        return;
      }

      setResult(data);

      const entry: BacktestHistoryEntry = {
        script_name: data.script_name,
        composite_score: data.composite_score,
        timestamp: new Date().toISOString(),
        url,
      };
      saveHistory(entry);
      setHistory(loadHistory());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unexpected error');
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="p-6 max-w-[900px] mx-auto">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <div className="w-2 h-2 rounded-full bg-terminal-green animate-pulse" />
          <h1 className="text-[10px] text-terminal-cyan tracking-[0.2em] uppercase">
            Research Lab
          </h1>
        </div>
        <div className="text-2xl font-bold terminal-glow tracking-wider">
          BACKTEST A SCRIPT
        </div>
        <div className="text-[10px] text-terminal-dim mt-1">
          Paste any TradingView indicator URL to get instant backtest results
        </div>
      </div>

      {/* Form */}
      <div className="panel p-5 mb-6">
        <BacktestForm
          onSubmit={handleSubmit}
          loading={loading}
          error={error}
        />
      </div>

      {/* Result */}
      {result && (
        <div className="mb-6">
          <BacktestReport result={result} />
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div>
          <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
            Recent Backtests
          </div>
          <div className="space-y-1">
            {history.map((entry, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between px-3 py-2 rounded border border-terminal-green/10 bg-terminal-bg-elevated/30 hover:bg-white/[0.02] transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-xs font-bold text-terminal-green truncate">
                    {entry.script_name}
                  </span>
                  <span className={`text-xs tabular-nums font-bold ${
                    entry.composite_score !== null && entry.composite_score > 0
                      ? 'text-terminal-green'
                      : entry.composite_score !== null && entry.composite_score < 0
                        ? 'text-terminal-red'
                        : 'text-terminal-dim'
                  }`}>
                    {entry.composite_score !== null ? entry.composite_score.toFixed(2) : '--'}
                  </span>
                </div>
                <span className="text-[9px] text-terminal-dim/50 flex-shrink-0 ml-3">
                  {new Date(entry.timestamp).toLocaleDateString()}{' '}
                  {new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
