'use client';

import { useState, useMemo } from 'react';
import type { TvIndicator } from '@/lib/research-types';
import IndicatorDetailPanel from './IndicatorDetailPanel';

type SortKey = keyof TvIndicator;
type SortDir = 'asc' | 'desc';

interface ScoreboardTableProps {
  indicators: TvIndicator[];
  onSelectIndicator: (name: string) => void;
}

function formatNum(val: number | null, decimals: number = 2): string {
  if (val === null || val === undefined) return '--';
  return val.toFixed(decimals);
}

function formatPct(val: number | null): string {
  if (val === null || val === undefined) return '--';
  return `${val.toFixed(1)}%`;
}

function valueColor(val: number | null): string {
  if (val === null || val === undefined) return 'text-terminal-dim';
  if (val > 0) return 'text-terminal-green';
  if (val < 0) return 'text-terminal-red';
  return 'text-terminal-amber';
}

export default function ScoreboardTable({ indicators, onSelectIndicator }: ScoreboardTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('composite_score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [expandedScript, setExpandedScript] = useState<string | null>(null);

  const sorted = useMemo(() => {
    return [...indicators].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }
      const diff = (aVal as number) - (bVal as number);
      return sortDir === 'asc' ? diff : -diff;
    });
  }, [indicators, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  function handleRowClick(scriptName: string) {
    if (expandedScript === scriptName) {
      setExpandedScript(null);
    } else {
      setExpandedScript(scriptName);
      onSelectIndicator(scriptName);
    }
  }

  const maxScore = useMemo(() => {
    return Math.max(...indicators.map(i => i.composite_score ?? 0), 1);
  }, [indicators]);

  const columns: { key: SortKey; label: string; align?: string }[] = [
    { key: 'rank', label: '#' },
    { key: 'script_name', label: 'SCRIPT NAME' },
    { key: 'category', label: 'CATEGORY' },
    { key: 'composite_score', label: 'SCORE' },
    { key: 'avg_sharpe', label: 'SHARPE' },
    { key: 'avg_roi', label: 'AVG ROI%' },
    { key: 'avg_win_rate', label: 'WIN RATE%' },
    { key: 'num_tickers_tested', label: 'TICKERS' },
    { key: 'best_ticker', label: 'BEST' },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-terminal-green/20">
            {columns.map(col => (
              <th
                key={col.key}
                onClick={() => handleSort(col.key)}
                className="text-[10px] uppercase tracking-wider text-terminal-cyan px-3 py-2 text-left cursor-pointer hover:text-terminal-cyan select-none whitespace-nowrap transition-colors"
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {sortKey === col.key && (
                    <span className="text-terminal-green text-[8px]">
                      {sortDir === 'desc' ? 'V' : '^'}
                    </span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((indicator, idx) => (
            <>
              <tr
                key={indicator.id}
                onClick={() => handleRowClick(indicator.script_name)}
                className={`border-b border-terminal-green/10 cursor-pointer transition-colors ${
                  idx % 2 === 0 ? 'bg-transparent' : 'bg-white/[0.01]'
                } hover:bg-white/[0.03] ${
                  expandedScript === indicator.script_name ? 'bg-terminal-cyan/[0.04] border-terminal-cyan/20' : ''
                }`}
              >
                {/* Rank */}
                <td className="px-3 py-2 text-xs tabular-nums text-terminal-dim">
                  {indicator.rank ?? idx + 1}
                </td>
                {/* Script Name */}
                <td className="px-3 py-2 text-xs font-bold text-terminal-green truncate max-w-[200px]">
                  {indicator.script_name}
                </td>
                {/* Category */}
                <td className="px-3 py-2">
                  <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border border-terminal-amber/30 text-terminal-amber bg-terminal-amber/10">
                    {indicator.category || '--'}
                  </span>
                </td>
                {/* Composite Score with bar */}
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs tabular-nums font-bold ${valueColor(indicator.composite_score)}`}>
                      {formatNum(indicator.composite_score)}
                    </span>
                    <div className="w-16 h-1.5 bg-terminal-bg-panel rounded-full overflow-hidden">
                      <div
                        className="h-full bg-terminal-green rounded-full transition-all"
                        style={{ width: `${Math.max(0, ((indicator.composite_score ?? 0) / maxScore) * 100)}%` }}
                      />
                    </div>
                  </div>
                </td>
                {/* Sharpe */}
                <td className={`px-3 py-2 text-xs tabular-nums font-bold ${valueColor(indicator.avg_sharpe)}`}>
                  {formatNum(indicator.avg_sharpe)}
                </td>
                {/* ROI */}
                <td className={`px-3 py-2 text-xs tabular-nums font-bold ${valueColor(indicator.avg_roi)}`}>
                  {formatPct(indicator.avg_roi)}
                </td>
                {/* Win Rate */}
                <td className={`px-3 py-2 text-xs tabular-nums font-bold ${valueColor(indicator.avg_win_rate)}`}>
                  {formatPct(indicator.avg_win_rate)}
                </td>
                {/* Tickers */}
                <td className="px-3 py-2 text-xs tabular-nums text-terminal-cyan">
                  {indicator.num_tickers_tested}
                </td>
                {/* Best Ticker */}
                <td className="px-3 py-2 text-xs font-bold text-terminal-green-dim">
                  {indicator.best_ticker || '--'}
                </td>
              </tr>
              {expandedScript === indicator.script_name && (
                <tr key={`${indicator.id}-detail`}>
                  <td colSpan={columns.length} className="p-0">
                    <IndicatorDetailPanel
                      scriptName={indicator.script_name}
                      onClose={() => setExpandedScript(null)}
                    />
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <div className="text-center py-12">
          <div className="text-terminal-dim text-sm">NO DATA</div>
          <div className="text-terminal-dim/50 text-xs mt-2">
            Run the TV script pipeline to populate indicators
          </div>
        </div>
      )}
    </div>
  );
}
