'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts';
import type { TvBacktest } from '@/lib/research-types';
import { formatNum, formatPct, valueColor, tvLink, mean, CHART_COLORS, CHART_TOOLTIP_STYLE } from '@/lib/research-utils';
import IndicatorRadar from './IndicatorRadar';

interface IndicatorDetailPanelProps {
  scriptName: string;
  scriptUrl: string | null;
  onClose: () => void;
}

/** Compute derived stats from backtests */
function computeStats(backtests: TvBacktest[]) {
  const success = backtests.filter(b => !b.error);
  if (success.length === 0) return null;

  const rois = success.map(b => b.roi_pct ?? 0);
  const sharpes = success.map(b => b.sharpe_ratio ?? 0);
  const winRates = success.map(b => b.win_rate_pct ?? 0);
  const drawdowns = success.map(b => b.max_drawdown_pct ?? 0);

  const avgRoi = mean(rois);
  const roiStdDev = Math.sqrt(rois.reduce((sum, v) => sum + (v - avgRoi) ** 2, 0) / rois.length);

  return {
    avgRoi,
    avgSharpe: mean(sharpes),
    avgWinRate: mean(winRates),
    worstDrawdown: Math.min(...drawdowns),
    consistency: roiStdDev,
  };
}

/** Group error messages by type for cleaner display */
function groupErrors(backtests: TvBacktest[]): { error: string; tickers: string[] }[] {
  const map = new Map<string, string[]>();
  for (const bt of backtests) {
    if (!bt.error) continue;
    const tickers = map.get(bt.error) ?? [];
    tickers.push(bt.ticker);
    map.set(bt.error, tickers);
  }
  return Array.from(map.entries()).map(([error, tickers]) => ({ error, tickers }));
}

export default function IndicatorDetailPanel({ scriptName, scriptUrl, onClose }: IndicatorDetailPanelProps) {
  const [backtests, setBacktests] = useState<TvBacktest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorsExpanded, setErrorsExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(`/api/research/backtests/${encodeURIComponent(scriptName)}`)
      .then(res => res.json())
      .then(data => {
        if (!cancelled) {
          setBacktests(data.backtests || []);
          setLoading(false);
        }
      })
      .catch(err => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [scriptName]);

  const successTests = backtests.filter(b => !b.error);
  const failedTests = backtests.filter(b => b.error);
  const stats = useMemo(() => computeStats(backtests), [backtests]);
  const groupedErrors = useMemo(() => groupErrors(backtests), [backtests]);

  const chartData = useMemo(() =>
    [...successTests]
      .sort((a, b) => (b.roi_pct ?? 0) - (a.roi_pct ?? 0))
      .map(b => ({ ticker: b.ticker, roi: b.roi_pct ?? 0 })),
    [successTests]
  );

  // Radar data: normalize each metric to 0-100
  const radarData = useMemo(() => {
    if (!stats) return null;
    return [
      { axis: 'Sharpe', value: Math.min(100, Math.max(0, stats.avgSharpe * 33.3)) },
      { axis: 'ROI', value: Math.min(100, Math.max(0, stats.avgRoi * 2)) },
      { axis: 'Win Rate', value: Math.min(100, Math.max(0, stats.avgWinRate)) },
      { axis: 'DD Resist', value: Math.min(100, Math.max(0, 100 + stats.worstDrawdown)) },
      { axis: 'Consistency', value: Math.min(100, Math.max(0, 100 - stats.consistency * 2)) },
    ];
  }, [stats]);

  return (
    <div className="border-t border-terminal-cyan/20 bg-terminal-bg-elevated/50 animate-fade-in">
      <div className="p-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <span className="text-[10px] text-terminal-cyan tracking-[0.15em] uppercase">
              Per-Ticker Breakdown
            </span>
            <span className="text-xs font-bold text-terminal-green">{scriptName}</span>
          </div>
          <button
            onClick={onClose}
            className="text-[10px] text-terminal-dim hover:text-terminal-red px-2 py-1 border border-terminal-dim/20 rounded hover:border-terminal-red/30 transition-colors"
          >
            CLOSE
          </button>
        </div>

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-3 py-4">
            <div className="grid grid-cols-5 gap-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-16 rounded bg-terminal-green/5 animate-pulse" />
              ))}
            </div>
            <div className="h-40 rounded bg-terminal-green/5 animate-pulse" />
          </div>
        )}

        {error && (
          <div className="text-terminal-red text-xs py-4 text-center">
            ERROR: {error}
          </div>
        )}

        {!loading && !error && (
          <div className="space-y-4">
            {/* Summary stat cards */}
            {stats && (
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {[
                  { label: 'AVG ROI', value: formatPct(stats.avgRoi), color: valueColor(stats.avgRoi) },
                  { label: 'AVG SHARPE', value: formatNum(stats.avgSharpe), color: valueColor(stats.avgSharpe) },
                  { label: 'AVG WIN RATE', value: formatPct(stats.avgWinRate), color: valueColor(stats.avgWinRate - 50) },
                  { label: 'WORST DD', value: formatPct(stats.worstDrawdown), color: 'text-terminal-red' },
                  { label: 'CONSISTENCY', value: formatNum(stats.consistency, 1), color: stats.consistency < 15 ? 'text-terminal-green' : 'text-terminal-amber' },
                ].map((card, i) => (
                  <div
                    key={card.label}
                    className="p-2.5 rounded border border-terminal-green/10 bg-terminal-bg-panel/40"
                    style={{ animationDelay: `${i * 80}ms` }}
                  >
                    <div className="text-[8px] text-terminal-dim tracking-[0.15em] uppercase">{card.label}</div>
                    <div className={`text-lg font-bold tabular-nums ${card.color}`}>{card.value}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Charts row: Radar + Bar */}
            <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4">
              {/* Radar chart — hidden on mobile */}
              {radarData && (
                <div className="hidden md:block">
                  <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
                    QUALITY SHAPE
                  </div>
                  <IndicatorRadar data={radarData} />
                </div>
              )}

              {/* ROI bar chart */}
              {chartData.length > 0 && (
                <div>
                  <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
                    ROI% by Ticker
                  </div>
                  <div className="h-40">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                        <XAxis
                          dataKey="ticker"
                          tick={{ fill: CHART_COLORS.amber, fontSize: 10 }}
                          axisLine={{ stroke: CHART_COLORS.axisLine }}
                          tickLine={false}
                        />
                        <YAxis
                          tick={{ fill: CHART_COLORS.greenDim, fontSize: 9 }}
                          axisLine={{ stroke: CHART_COLORS.axisLine }}
                          tickLine={false}
                          tickFormatter={(v: number) => `${v}%`}
                        />
                        <ReferenceLine y={0} stroke={CHART_COLORS.greenDim} strokeDasharray="3 3" />
                        <Tooltip
                          contentStyle={CHART_TOOLTIP_STYLE}
                          formatter={(value: number | undefined) => [`${(value ?? 0).toFixed(1)}%`, 'ROI']}
                        />
                        <Bar dataKey="roi" radius={[2, 2, 0, 0]}>
                          {chartData.map((entry, idx) => (
                            <Cell
                              key={idx}
                              fill={entry.roi >= 0 ? CHART_COLORS.green : CHART_COLORS.red}
                              fillOpacity={0.7}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </div>

            {/* Per-ticker stats table */}
            {successTests.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-terminal-cyan/20">
                      {['TICKER', 'ROI%', 'SHARPE', 'WIN RATE%', 'MAX DD%', 'PROFIT F', '# TRADES'].map(h => (
                        <th key={h} className="text-[9px] uppercase tracking-wider text-terminal-cyan/70 px-3 py-1.5 text-left">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {successTests.map(bt => (
                      <tr key={bt.id} className="border-b border-terminal-green/5 hover:bg-white/[0.02]">
                        <td className="px-3 py-1.5 font-bold text-terminal-amber">{bt.ticker}</td>
                        <td className={`px-3 py-1.5 tabular-nums font-bold ${valueColor(bt.roi_pct)}`}>
                          {formatPct(bt.roi_pct)}
                        </td>
                        <td className={`px-3 py-1.5 tabular-nums ${valueColor(bt.sharpe_ratio)}`}>
                          {formatNum(bt.sharpe_ratio)}
                        </td>
                        <td className={`px-3 py-1.5 tabular-nums ${valueColor(bt.win_rate_pct)}`}>
                          {formatPct(bt.win_rate_pct)}
                        </td>
                        <td className="px-3 py-1.5 tabular-nums text-terminal-red">
                          {formatPct(bt.max_drawdown_pct)}
                        </td>
                        <td className={`px-3 py-1.5 tabular-nums ${valueColor(bt.profit_factor !== null ? bt.profit_factor - 1 : null)}`}>
                          {formatNum(bt.profit_factor)}
                        </td>
                        <td className="px-3 py-1.5 tabular-nums text-terminal-dim">
                          {bt.num_trades ?? '--'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Grouped errors */}
            {groupedErrors.length > 0 && (
              <div className="mt-2">
                <button
                  onClick={() => setErrorsExpanded(!errorsExpanded)}
                  className="text-[9px] text-terminal-amber tracking-[0.15em] uppercase mb-1 flex items-center gap-1 hover:text-terminal-amber-bright transition-colors"
                >
                  ERRORS ({failedTests.length})
                  <svg width="8" height="5" viewBox="0 0 8 5" fill="none" className={`transition-transform ${errorsExpanded ? 'rotate-180' : ''}`}>
                    <path d="M4 5L0 0H8L4 5Z" fill="currentColor" />
                  </svg>
                </button>
                <div className="space-y-1">
                  {groupedErrors.map(group => (
                    <div
                      key={group.error}
                      className="text-[10px] px-2 py-1 rounded bg-terminal-red/5 border border-terminal-red/20"
                    >
                      <span className="text-terminal-red/70">{group.tickers.length}x &quot;{group.error}&quot;</span>
                      {errorsExpanded && (
                        <span className="text-terminal-amber font-bold ml-2">
                          [{group.tickers.join(', ')}]
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {successTests.length === 0 && failedTests.length === 0 && (
              <div className="text-center py-4 text-terminal-dim text-xs">
                No backtest data available
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-3 mt-2">
              <a
                href={tvLink(scriptUrl, scriptName)}
                target="_blank"
                rel="noopener noreferrer"
                className="flex-1 flex items-center justify-center gap-2 py-2 text-[10px] font-bold tracking-wider border border-terminal-cyan/40 text-terminal-cyan rounded hover:bg-terminal-cyan/10 hover:border-terminal-cyan transition-all"
              >
                VIEW ON TRADINGVIEW
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path d="M10 6.5V10a1 1 0 01-1 1H2a1 1 0 01-1-1V3a1 1 0 011-1h3.5M7 1h4v4M5 7l6-6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </a>
              {scriptUrl && (
                <a
                  href={`/research/backtest?url=${encodeURIComponent(scriptUrl)}`}
                  className="flex-1 flex items-center justify-center gap-2 py-2 text-[10px] font-bold tracking-wider border border-terminal-green/40 text-terminal-green rounded hover:bg-terminal-green/10 hover:border-terminal-green transition-all"
                >
                  RE-RUN BACKTEST
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M1 6a5 5 0 019-3M11 6a5 5 0 01-9 3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
                    <path d="M10 1v2h-2M2 11V9h2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
