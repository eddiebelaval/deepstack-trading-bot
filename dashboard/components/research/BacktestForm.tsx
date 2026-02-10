'use client';

import { useState } from 'react';

interface BacktestFormProps {
  onSubmit: (url: string) => Promise<void>;
  loading: boolean;
  error: string | null;
}

export default function BacktestForm({ onSubmit, loading, error }: BacktestFormProps) {
  const [url, setUrl] = useState('');

  const isValid = url.includes('tradingview.com/script/');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isValid || loading) return;
    await onSubmit(url);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label className="block text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-1.5">
          TradingView Script URL
        </label>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.tradingview.com/script/ABC123/..."
          disabled={loading}
          className="w-full bg-terminal-bg-panel border border-terminal-green/20 text-terminal-green text-sm px-3 py-2.5 rounded focus:border-terminal-cyan/50 focus:outline-none placeholder:text-terminal-dim/30 disabled:opacity-50 transition-colors"
        />
        {url && !isValid && (
          <div className="text-[10px] text-terminal-amber mt-1">
            URL must contain tradingview.com/script/
          </div>
        )}
      </div>

      <button
        type="submit"
        disabled={!isValid || loading}
        className={`w-full py-2.5 text-xs font-bold border rounded transition-all duration-200 ${
          loading
            ? 'border-terminal-amber bg-terminal-amber/10 text-terminal-amber animate-pulse cursor-wait'
            : isValid
              ? 'border-terminal-green text-terminal-green hover:bg-terminal-green/15 hover:shadow-[0_0_15px_rgba(0,255,65,0.2)] cursor-pointer'
              : 'border-terminal-dim/20 text-terminal-dim/40 cursor-not-allowed'
        }`}
      >
        {loading ? 'PROCESSING...' : 'RUN BACKTEST'}
      </button>

      {error && (
        <div className="text-xs px-3 py-2 rounded border border-terminal-red/30 bg-terminal-red/5 text-terminal-red">
          {error}
        </div>
      )}
    </form>
  );
}
