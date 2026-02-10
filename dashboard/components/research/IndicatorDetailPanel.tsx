'use client';

import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import type { TvBacktest } from '@/lib/research-types';

interface IndicatorDetailPanelProps {
  scriptName: string;
  onClose: () => void;
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

export default function IndicatorDetailPanel({ scriptName, onClose }: IndicatorDetailPanelProps) {
  const [backtests, setBacktests] = useState<TvBacktest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  const chartData = successTests.map(b => ({
    ticker: b.ticker,
    roi: b.roi_pct ?? 0,
  }));

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

        {loading && (
          <div className="text-terminal-green text-xs animate-pulse py-4 text-center">
            LOADING...
          </div>
        )}

        {error && (
          <div className="text-terminal-red text-xs py-4 text-center">
            ERROR: {error}
          </div>
        )}

        {!loading && !error && (
          <div className="space-y-4">
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

            {/* ROI bar chart */}
            {chartData.length > 0 && (
              <div className="mt-2">
                <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
                  ROI% by Ticker
                </div>
                <div className="h-32">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                      <XAxis
                        dataKey="ticker"
                        tick={{ fill: '#FFBF00', fontSize: 10 }}
                        axisLine={{ stroke: 'rgba(0,255,65,0.2)' }}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fill: '#00AA2B', fontSize: 9 }}
                        axisLine={{ stroke: 'rgba(0,255,65,0.2)' }}
                        tickLine={false}
                        tickFormatter={(v: number) => `${v}%`}
                      />
                      <Tooltip
                        contentStyle={{
                          background: '#16161f',
                          border: '1px solid rgba(0,255,65,0.3)',
                          borderRadius: '4px',
                          fontSize: '11px',
                          color: '#00FF41',
                        }}
                        formatter={(value: number | undefined) => [`${(value ?? 0).toFixed(1)}%`, 'ROI']}
                      />
                      <Bar dataKey="roi" radius={[2, 2, 0, 0]}>
                        {chartData.map((entry, idx) => (
                          <Cell
                            key={idx}
                            fill={entry.roi >= 0 ? '#00FF41' : '#FF0000'}
                            fillOpacity={0.7}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Failed tickers */}
            {failedTests.length > 0 && (
              <div className="mt-2">
                <div className="text-[9px] text-terminal-amber tracking-[0.15em] uppercase mb-1">
                  Errors ({failedTests.length})
                </div>
                <div className="space-y-1">
                  {failedTests.map(bt => (
                    <div
                      key={bt.id}
                      className="text-[10px] px-2 py-1 rounded bg-terminal-red/5 border border-terminal-red/20"
                    >
                      <span className="text-terminal-amber font-bold">{bt.ticker}</span>
                      <span className="text-terminal-red/70 ml-2">{bt.error}</span>
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
          </div>
        )}
      </div>
    </div>
  );
}
