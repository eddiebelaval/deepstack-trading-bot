'use client';

import { useState, useMemo, Fragment } from 'react';
import type { TvIndicator } from '@/lib/research-types';
import { formatNum, formatPct, valueColor, tvLink } from '@/lib/research-utils';
import IndicatorDetailPanel from './IndicatorDetailPanel';

type SortKey = keyof TvIndicator;
type SortDir = 'asc' | 'desc';

interface ScoreboardTableProps {
  indicators: TvIndicator[];
  expandedScript?: string | null;
  onToggleExpand?: (scriptName: string) => void;
}

/** Inline SVG chevron — points up or down */
function SortChevron({ direction, active }: { direction: 'up' | 'down'; active: boolean }) {
  const color = active ? '#00FF41' : 'rgba(0,170,43,0.3)';
  return (
    <svg width="8" height="5" viewBox="0 0 8 5" fill="none" className="inline-block">
      {direction === 'up' ? (
        <path d="M4 0L8 5H0L4 0Z" fill={color} />
      ) : (
        <path d="M4 5L0 0H8L4 5Z" fill={color} />
      )}
    </svg>
  );
}

export default function ScoreboardTable({
  indicators,
  expandedScript: externalExpanded,
  onToggleExpand,
}: ScoreboardTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('composite_score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [internalExpanded, setInternalExpanded] = useState<string | null>(null);

  // Allow parent to control expanded state, fallback to internal
  const expandedScript = externalExpanded !== undefined ? externalExpanded : internalExpanded;

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
    if (onToggleExpand) {
      onToggleExpand(scriptName);
    } else {
      setInternalExpanded(prev => prev === scriptName ? null : scriptName);
    }
  }

  const maxScore = useMemo(() => {
    return Math.max(...indicators.map(i => i.composite_score ?? 0), 1);
  }, [indicators]);

  const columns: { key: SortKey; label: string }[] = [
    { key: 'rank', label: '#' },
    { key: 'script_name', label: 'SCRIPT NAME' },
    { key: 'category', label: 'CATEGORY' },
    { key: 'composite_score', label: 'SCORE' },
    { key: 'avg_sharpe', label: 'SHARPE' },
    { key: 'avg_roi', label: 'AVG ROI%' },
    { key: 'avg_win_rate', label: 'WIN RATE%' },
    { key: 'num_tickers_tested', label: 'TICKERS' },
    { key: 'best_ticker', label: 'BEST' },
    { key: 'worst_ticker', label: 'WORST' },
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
                  <span className="inline-flex flex-col gap-px ml-0.5">
                    <SortChevron direction="up" active={sortKey === col.key && sortDir === 'asc'} />
                    <SortChevron direction="down" active={sortKey === col.key && sortDir === 'desc'} />
                  </span>
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((indicator, idx) => (
            <Fragment key={indicator.id}>
              <tr
                onClick={() => handleRowClick(indicator.script_name)}
                className={[
                  'border-b border-terminal-green/10 cursor-pointer transition-all duration-200 hover:bg-white/[0.03]',
                  idx % 2 === 0 ? 'bg-transparent' : 'bg-white/[0.01]',
                  expandedScript === indicator.script_name && 'bg-terminal-cyan/[0.04] border-terminal-cyan/20',
                  expandedScript && expandedScript !== indicator.script_name ? 'opacity-60' : 'opacity-100',
                ].filter(Boolean).join(' ')}
              >
                {/* Rank */}
                <td className="px-3 py-2 text-xs tabular-nums text-terminal-dim">
                  {indicator.rank ?? idx + 1}
                </td>
                {/* Script Name + TV link */}
                <td className="px-3 py-2 text-xs font-bold text-terminal-green max-w-[200px]">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate">{indicator.script_name}</span>
                    <a
                      href={tvLink(indicator.script_url, indicator.script_name)}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="flex-shrink-0 text-terminal-cyan/50 hover:text-terminal-cyan transition-colors"
                      title="View on TradingView"
                    >
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                        <path d="M10 6.5V10a1 1 0 01-1 1H2a1 1 0 01-1-1V3a1 1 0 011-1h3.5M7 1h4v4M5 7l6-6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </a>
                  </span>
                </td>
                {/* Category */}
                <td className="px-3 py-2">
                  <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border border-terminal-amber/30 text-terminal-amber bg-terminal-amber/10">
                    {indicator.category || '--'}
                  </span>
                </td>
                {/* Composite Score with bar */}
                <td className="px-3 py-2 min-w-[120px]">
                  <div className="flex items-center gap-2">
                    <span className={`text-sm tabular-nums font-bold terminal-glow ${valueColor(indicator.composite_score)}`}>
                      {formatNum(indicator.composite_score)}
                    </span>
                    <div className="w-16 h-1.5 bg-terminal-bg-panel rounded-full overflow-hidden group-hover:w-20 transition-all">
                      <div
                        className="h-full bg-terminal-green rounded-full transition-all duration-500"
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
                {/* Worst Ticker */}
                <td className="px-3 py-2 text-xs font-bold text-terminal-red">
                  {indicator.worst_ticker || '--'}
                </td>
              </tr>
              {expandedScript === indicator.script_name && (
                <tr>
                  <td colSpan={columns.length} className="p-0">
                    <IndicatorDetailPanel
                      scriptName={indicator.script_name}
                      scriptUrl={indicator.script_url ?? null}
                      onClose={() => handleRowClick(indicator.script_name)}
                    />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <div className="text-center py-12">
          <div className="text-terminal-dim text-sm">NO DATA</div>
          <div className="text-terminal-dim/50 text-xs mt-2">
            Run the TV script pipeline to populate indicators.{' '}
            <a href="/research/backtest" className="text-terminal-cyan hover:underline">
              Run a backtest
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
