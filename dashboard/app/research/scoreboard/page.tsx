'use client';

import { Suspense, useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import type { TvIndicator } from '@/lib/research-types';
import ScoreboardTable from '@/components/research/ScoreboardTable';
import ScoreboardSummary from '@/components/research/ScoreboardSummary';

function ScoreboardPageInner() {
  const searchParams = useSearchParams();
  const highlightRef = useRef<string | null>(searchParams.get('highlight'));

  const [indicators, setIndicators] = useState<TvIndicator[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  // Filters
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [minSharpe, setMinSharpe] = useState<string>('');
  const [minTrades, setMinTrades] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Expanded row (controlled from page for highlight support)
  const [expandedScript, setExpandedScript] = useState<string | null>(
    highlightRef.current
  );

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

  // Client-side filtering
  const filtered = indicators.filter(ind => {
    if (minSharpe && (ind.avg_sharpe === null || ind.avg_sharpe < parseFloat(minSharpe))) {
      return false;
    }
    if (minTrades && ind.num_tickers_tested < parseInt(minTrades, 10)) {
      return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      if (!ind.script_name.toLowerCase().includes(q)) {
        return false;
      }
    }
    return true;
  });

  // Extract unique categories for the dropdown
  const categories = [...new Set(indicators.map(i => i.category).filter(Boolean))].sort();

  const hasFilters = !!(categoryFilter || minSharpe || minTrades || searchQuery);

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

      {/* Summary dashboard */}
      {!loading && !error && filtered.length > 0 && (
        <ScoreboardSummary indicators={filtered} />
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4 mb-4 p-3 rounded border border-terminal-green/10 bg-terminal-bg-elevated/30">
        <div>
          <label className="block text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-1">
            Search
          </label>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Script name..."
            className="bg-terminal-bg-panel border border-terminal-green/20 text-terminal-green text-xs px-2 py-1.5 rounded w-40 focus:border-terminal-cyan/50 focus:outline-none placeholder:text-terminal-dim/30"
          />
        </div>
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
        {hasFilters && (
          <button
            onClick={() => { setCategoryFilter(''); setMinSharpe(''); setMinTrades(''); setSearchQuery(''); }}
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
            <div className="text-terminal-green text-sm">
              LOADING<span className="animate-cursor-blink">_</span>
            </div>
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
            expandedScript={expandedScript}
            onToggleExpand={(name) => setExpandedScript(prev => prev === name ? null : name)}
          />
        )}
      </div>
    </div>
  );
}

export default function ScoreboardPage() {
  return (
    <Suspense fallback={
      <div className="p-6 max-w-[1400px] mx-auto">
        <div className="text-terminal-green text-sm text-center py-12">
          LOADING<span className="animate-cursor-blink">_</span>
        </div>
      </div>
    }>
      <ScoreboardPageInner />
    </Suspense>
  );
}
