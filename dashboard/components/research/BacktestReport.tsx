'use client';

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import type { BacktestResult } from '@/lib/research-types';
import { formatNum, formatPct, valueColor, CHART_COLORS, CHART_TOOLTIP_STYLE } from '@/lib/research-utils';

interface BacktestReportProps {
  result: BacktestResult;
}

export default function BacktestReport({ result }: BacktestReportProps) {
  const successTickers = result.tickers.filter(t => !t.error);
  const failedTickers = result.tickers.filter(t => t.error);

  const chartData = successTickers.map(t => ({
    ticker: t.ticker,
    roi: t.roi_pct ?? 0,
  }));

  const maxScore = Math.max(result.composite_score ?? 0, result.scoreboard_avg ?? 0, 1);

  return (
    <div className="panel animate-fade-in">
      <div className="p-5 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[10px] text-terminal-cyan tracking-[0.15em] uppercase mb-1">
              Backtest Result
            </div>
            <div className="text-lg font-bold terminal-glow tracking-wide">
              {result.script_name}
            </div>
            {result.category && (
              <span className="inline-block mt-1 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border border-terminal-amber/30 text-terminal-amber bg-terminal-amber/10">
                {result.category}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {result.saved_to_scoreboard && (
              <span className="text-[9px] font-bold px-2 py-1 rounded border border-terminal-green/30 text-terminal-green bg-terminal-green/10">
                SAVED TO SCOREBOARD
              </span>
            )}
            <a
              href="/research/scoreboard"
              className="text-[9px] font-bold px-2 py-1 rounded border border-terminal-cyan/30 text-terminal-cyan hover:bg-terminal-cyan/10 transition-colors"
            >
              VIEW SCOREBOARD
            </a>
          </div>
        </div>

        {/* Composite Score */}
        <div className="p-3 rounded border border-terminal-green/15 bg-terminal-bg-panel/40">
          <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
            Composite Score
          </div>
          <div className="flex items-center gap-4">
            <span className={`text-2xl font-bold tabular-nums ${valueColor(result.composite_score)}`}>
              {formatNum(result.composite_score)}
            </span>
            <div className="flex-1">
              <div className="w-full h-2 bg-terminal-bg rounded-full overflow-hidden">
                <div
                  className="h-full bg-terminal-green rounded-full transition-all"
                  style={{ width: `${Math.max(0, ((result.composite_score ?? 0) / maxScore) * 100)}%` }}
                />
              </div>
            </div>
          </div>
          {result.scoreboard_avg !== null && (
            <div className="flex items-center gap-4 mt-2 text-[10px]">
              <span className="text-terminal-dim">Scoreboard Average:</span>
              <span className="text-terminal-cyan tabular-nums font-bold">{formatNum(result.scoreboard_avg)}</span>
              <span className="text-terminal-dim/50">vs</span>
              <span className="text-terminal-dim">This Script:</span>
              <span className={`tabular-nums font-bold ${valueColor(result.composite_score)}`}>
                {formatNum(result.composite_score)}
              </span>
              {result.composite_score !== null && result.scoreboard_avg !== null && (
                <span className={`font-bold ${result.composite_score >= result.scoreboard_avg ? 'text-terminal-green' : 'text-terminal-red'}`}>
                  ({result.composite_score >= result.scoreboard_avg ? 'ABOVE' : 'BELOW'} AVG)
                </span>
              )}
            </div>
          )}
        </div>

        {/* Per-ticker results */}
        {successTickers.length > 0 && (
          <div>
            <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
              Per-Ticker Results ({successTickers.length})
            </div>
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
                  {successTickers.map((t, idx) => (
                    <tr key={idx} className="border-b border-terminal-green/5 hover:bg-white/[0.02]">
                      <td className="px-3 py-1.5 font-bold text-terminal-amber">{t.ticker}</td>
                      <td className={`px-3 py-1.5 tabular-nums font-bold ${valueColor(t.roi_pct)}`}>
                        {formatPct(t.roi_pct)}
                      </td>
                      <td className={`px-3 py-1.5 tabular-nums ${valueColor(t.sharpe_ratio)}`}>
                        {formatNum(t.sharpe_ratio)}
                      </td>
                      <td className={`px-3 py-1.5 tabular-nums ${valueColor(t.win_rate_pct)}`}>
                        {formatPct(t.win_rate_pct)}
                      </td>
                      <td className="px-3 py-1.5 tabular-nums text-terminal-red">
                        {formatPct(t.max_drawdown_pct)}
                      </td>
                      <td className={`px-3 py-1.5 tabular-nums ${valueColor(t.profit_factor !== null ? t.profit_factor - 1 : null)}`}>
                        {formatNum(t.profit_factor)}
                      </td>
                      <td className="px-3 py-1.5 tabular-nums text-terminal-dim">
                        {t.num_trades ?? '--'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ROI chart */}
        {chartData.length > 0 && (
          <div>
            <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
              ROI% by Ticker
            </div>
            <div className="h-36">
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

        {/* Failed tickers */}
        {failedTickers.length > 0 && (
          <div>
            <div className="text-[9px] text-terminal-amber tracking-[0.15em] uppercase mb-1">
              Errors ({failedTickers.length})
            </div>
            <div className="space-y-1">
              {failedTickers.map((t, idx) => (
                <div
                  key={idx}
                  className="text-[10px] px-2 py-1 rounded bg-terminal-red/5 border border-terminal-red/20"
                >
                  <span className="text-terminal-amber font-bold">{t.ticker}</span>
                  <span className="text-terminal-red/70 ml-2">{t.error}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
