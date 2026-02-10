'use client';

import { useState, useEffect, useCallback } from 'react';
import type { TvIndicator } from '@/lib/research-types';
import ScoreboardTable from '@/components/research/ScoreboardTable';

export default function ScoreboardPage() {
  const [indicators, setIndicators] = useState<TvIndicator[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  // Filters
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [minSharpe, setMinSharpe] = useState<string>('');
  const [minTrades, setMinTrades] = useState<string>('');

  const fetchIndicators = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      params.set('limit', '200');
      if (categoryFilter) params.set('category', categoryFilter);

      const res = await fetch(`/api/research/indicators?${params}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
      } else {
        setIndicators(data.indicators || []);
        setLastUpdated(new Date().toLocaleTimeString());
        setError(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch');
    } finally {
      setLoading(false);
    }
  }, [categoryFilter]);

  useEffect(() => {
    fetchIndicators();
    const interval = setInterval(fetchIndicators, 60_000);
    return () => clearInterval(interval);
  }, [fetchIndicators]);

  // Client-side filtering for Sharpe and trades
  const filtered = indicators.filter(ind => {
    if (minSharpe && (ind.avg_sharpe === null || ind.avg_sharpe < parseFloat(minSharpe))) {
      return false;
    }
    if (minTrades && ind.num_tickers_tested < parseInt(minTrades, 10)) {
      return false;
    }
    return true;
  });

  // Extract unique categories for the dropdown
  const categories = [...new Set(indicators.map(i => i.category).filter(Boolean))].sort();

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <div className="w-2 h-2 rounded-full bg-terminal-cyan animate-pulse" />
          <h1 className="text-[10px] text-terminal-cyan tracking-[0.2em] uppercase">
            Research Lab
          </h1>
        </div>
        <div className="text-2xl font-bold terminal-glow tracking-wider">
          TV SCRIPT SCOREBOARD
        </div>
        <div className="text-[10px] text-terminal-dim mt-1 flex items-center gap-4">
          <span>{filtered.length} of {indicators.length} indicators</span>
          {lastUpdated && (
            <span className="text-terminal-dim/50">
              Updated {lastUpdated} (auto-refresh 60s)
            </span>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4 mb-4 p-3 rounded border border-terminal-green/10 bg-terminal-bg-elevated/30">
        <div>
          <label className="block text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-1">
            Category
          </label>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="bg-terminal-bg-panel border border-terminal-green/20 text-terminal-green text-xs px-2 py-1.5 rounded focus:border-terminal-cyan/50 focus:outline-none"
          >
            <option value="">ALL</option>
            {categories.map(cat => (
              <option key={cat} value={cat}>{cat.toUpperCase()}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-1">
            Min Sharpe
          </label>
          <input
            type="number"
            step="0.1"
            value={minSharpe}
            onChange={(e) => setMinSharpe(e.target.value)}
            placeholder="0.0"
            className="bg-terminal-bg-panel border border-terminal-green/20 text-terminal-green text-xs px-2 py-1.5 rounded w-20 focus:border-terminal-cyan/50 focus:outline-none tabular-nums"
          />
        </div>
        <div>
          <label className="block text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-1">
            Min Tickers
          </label>
          <input
            type="number"
            step="1"
            value={minTrades}
            onChange={(e) => setMinTrades(e.target.value)}
            placeholder="0"
            className="bg-terminal-bg-panel border border-terminal-green/20 text-terminal-green text-xs px-2 py-1.5 rounded w-20 focus:border-terminal-cyan/50 focus:outline-none tabular-nums"
          />
        </div>
        {(categoryFilter || minSharpe || minTrades) && (
          <button
            onClick={() => { setCategoryFilter(''); setMinSharpe(''); setMinTrades(''); }}
            className="text-[10px] text-terminal-dim hover:text-terminal-red px-2 py-1.5 border border-terminal-dim/20 rounded hover:border-terminal-red/30 transition-colors"
          >
            CLEAR
          </button>
        )}
      </div>

      {/* Content */}
      <div className="panel">
        {loading ? (
          <div className="text-center py-12">
            <div className="text-terminal-green text-sm animate-pulse">LOADING...</div>
          </div>
        ) : error ? (
          <div className="text-center py-12">
            <div className="text-terminal-red text-sm">ERROR: {error}</div>
            <button
              onClick={fetchIndicators}
              className="mt-3 text-xs text-terminal-cyan border border-terminal-cyan/30 px-3 py-1 rounded hover:bg-terminal-cyan/10 transition-colors"
            >
              RETRY
            </button>
          </div>
        ) : (
          <ScoreboardTable
            indicators={filtered}
            onSelectIndicator={() => {}}
          />
        )}
      </div>
    </div>
  );
}
