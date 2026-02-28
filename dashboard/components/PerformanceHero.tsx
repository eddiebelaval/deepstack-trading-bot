'use client';

import { useState, useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import {
  formatDollars,
  formatChartLabel,
  resolvePeriod,
} from '@/lib/analytics';
import type { PeriodName, ChartInterval } from '@/lib/analytics';

type TimeFrame = '1D' | '1W' | '1M' | '3M' | '1Y' | 'ALL';

interface BalanceSnapshot {
  timestamp: string;
  balance_cents: number;
  available_balance_cents: number;
}

interface PerformanceHeroProps {
  balanceHistory?: BalanceSnapshot[];
}

const COLORS = {
  profit: { line: '#22c55e', glow: 'rgba(34, 197, 94, 0.5)' },
  loss: { line: '#ef4444', glow: 'rgba(239, 68, 68, 0.5)' },
};

// Map existing UI timeframes to PeriodName values
const TIMEFRAME_TO_PERIOD: Record<TimeFrame, PeriodName> = {
  '1D': '1D',
  '1W': '7D',
  '1M': '30D',
  '3M': '90D',
  '1Y': 'YTD',
  'ALL': 'ALL',
};

// Map UI timeframes to chart intervals for label formatting
function getChartInterval(tf: TimeFrame): ChartInterval {
  return resolvePeriod(TIMEFRAME_TO_PERIOD[tf]).interval;
}

export default function PerformanceHero({ balanceHistory }: PerformanceHeroProps) {
  const [timeframe, setTimeframe] = useState<TimeFrame>('1D');
  const timeframes: TimeFrame[] = ['1D', '1W', '1M', '3M', '1Y', 'ALL'];

  // Filter balance history by selected timeframe
  const filteredData = useMemo(() => {
    if (!balanceHistory?.length) return [];
    // API returns desc order -- reverse to chronological
    const chrono = [...balanceHistory].reverse();
    if (timeframe === 'ALL') return chrono;
    const period = resolvePeriod(TIMEFRAME_TO_PERIOD[timeframe]);
    return chrono.filter(d => new Date(d.timestamp) >= period.startDate);
  }, [balanceHistory, timeframe]);

  // Compute chart data + stats from the filtered window
  const { chartData, stats } = useMemo(() => {
    if (filteredData.length < 2) return { chartData: [], stats: null };
    const startCents = filteredData[0].balance_cents;
    const endCents = filteredData[filteredData.length - 1].balance_cents;
    const values = filteredData.map(d => d.balance_cents);
    const changeCents = endCents - startCents;
    const changePct = startCents > 0 ? (changeCents / startCents) * 100 : 0;
    const endEntry = filteredData[filteredData.length - 1];
    const positionCents = endEntry.balance_cents - endEntry.available_balance_cents;
    const interval = getChartInterval(timeframe);

    return {
      chartData: filteredData.map(entry => ({
        timestamp: entry.timestamp,
        value: entry.balance_cents / 100,
        label: formatChartLabel(entry.timestamp, interval),
      })),
      stats: {
        currentCents: endCents,
        startCents,
        highCents: Math.max(...values),
        lowCents: Math.min(...values),
        changeCents,
        changePct,
        isProfit: changeCents >= 0,
        cashCents: endEntry.available_balance_cents,
        positionCents,
      },
    };
  }, [filteredData, timeframe]);

  const colors = stats?.isProfit ? COLORS.profit : COLORS.loss;

  // Custom tooltip
  const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) => {
    if (active && payload?.length && stats) {
      const dollars = payload[0].value;
      const fromStart = (dollars * 100) - stats.startCents;
      const isUp = fromStart >= 0;
      return (
        <div className="bg-terminal-bg-panel/95 backdrop-blur border border-white/10 rounded-lg p-3 text-xs font-mono shadow-xl">
          <div className="text-terminal-dim mb-2">{label}</div>
          <div className={`text-2xl font-bold ${isUp ? 'text-green-400' : 'text-red-400'}`}>
            ${dollars.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className={`text-sm mt-1 ${isUp ? 'text-green-400/70' : 'text-red-400/70'}`}>
            {isUp ? '+' : ''}{formatDollars(fromStart)} from period start
          </div>
        </div>
      );
    }
    return null;
  };

  if (!stats || chartData.length === 0) {
    return (
      <div className="panel panel-hero p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-xs text-terminal-dim mb-1 tracking-wider">PORTFOLIO VALUE</div>
            <div className="text-4xl font-bold tabular-nums text-terminal-dim/40">---</div>
          </div>
          <div className="flex gap-1 bg-terminal-bg rounded-lg p-1">
            {timeframes.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${
                  timeframe === tf ? 'bg-white/10 text-white/60 border border-white/20' : 'text-terminal-dim hover:text-white hover:bg-white/5'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
        <div className="h-72 flex items-center justify-center">
          <div className="text-center">
            <div className="text-terminal-dim/40 text-sm mb-2">NO TRADING DATA</div>
            <div className="text-terminal-dim/30 text-xs">Start the bot to begin collecting performance data</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="panel panel-hero p-6">
      {/* Header: balance + change + timeframe selector */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="text-xs text-terminal-dim mb-1 tracking-wider">PORTFOLIO VALUE</div>
          <div className="flex items-baseline gap-3">
            <span
              className="text-4xl font-bold tabular-nums text-white"
              style={{ textShadow: '0 0 20px rgba(255,255,255,0.15)' }}
            >
              {formatDollars(stats.currentCents)}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-1">
            <span className={`text-lg font-bold tabular-nums ${stats.isProfit ? 'text-green-400' : 'text-red-400'}`}
              style={{ textShadow: `0 0 12px ${colors.glow}` }}>
              {stats.changeCents >= 0 ? '+' : ''}{formatDollars(stats.changeCents)}
            </span>
            <span className={`text-sm font-medium ${stats.isProfit ? 'text-green-400/70' : 'text-red-400/70'}`}>
              ({stats.changePct >= 0 ? '+' : ''}{stats.changePct.toFixed(2)}%)
            </span>
            <span className="text-xs text-terminal-dim">
              {timeframe === 'ALL' ? 'all time' : timeframe === '1D' ? 'today' : `past ${timeframe.replace('1', '1 ').replace('3', '3 ')}`}
            </span>
          </div>
        </div>

        {/* Timeframe selector */}
        <div className="flex gap-1 bg-terminal-bg rounded-lg p-1">
          {timeframes.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${
                timeframe === tf
                  ? `${stats.isProfit ? 'bg-green-500/20 text-green-400 border border-green-500/40' : 'bg-red-500/20 text-red-400 border border-red-500/40'}`
                  : 'text-terminal-dim hover:text-white hover:bg-white/5'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="h-72 -mx-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="profitGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.profit.line} stopOpacity={0.35} />
                <stop offset="50%" stopColor={COLORS.profit.line} stopOpacity={0.1} />
                <stop offset="100%" stopColor={COLORS.profit.line} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="lossGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.loss.line} stopOpacity={0.35} />
                <stop offset="50%" stopColor={COLORS.loss.line} stopOpacity={0.1} />
                <stop offset="100%" stopColor={COLORS.loss.line} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(255,255,255,0.05)"
              vertical={false}
            />
            <XAxis
              dataKey="label"
              tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }}
              axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => `$${v}`}
              domain={['dataMin - 5', 'dataMax + 5']}
              width={55}
            />
            <Tooltip content={<CustomTooltip />} />

            {/* Reference line at period start value */}
            <ReferenceLine
              y={stats.startCents / 100}
              stroke="rgba(255,255,255,0.2)"
              strokeDasharray="4 4"
            />

            <Area
              type="monotone"
              dataKey="value"
              stroke={colors.line}
              strokeWidth={2.5}
              fill={`url(#${stats.isProfit ? 'profitGradient' : 'lossGradient'})`}
              dot={false}
              activeDot={{
                r: 5,
                fill: colors.line,
                stroke: '#1e1e28',
                strokeWidth: 2,
              }}
              style={{
                filter: `drop-shadow(0 0 8px ${colors.glow})`,
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-5 gap-3 mt-4 pt-4 border-t border-white/5">
        <div>
          <div className="text-xs text-terminal-dim mb-1">CASH</div>
          <div className="text-base font-bold tabular-nums text-terminal-cyan">
            {formatDollars(stats.cashCents)}
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-dim mb-1">POSITIONS</div>
          <div className="text-base font-bold tabular-nums text-terminal-amber">
            {formatDollars(stats.positionCents)}
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-dim mb-1">HIGH</div>
          <div className="text-base font-bold tabular-nums text-green-400">
            {formatDollars(stats.highCents)}
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-dim mb-1">LOW</div>
          <div className={`text-base font-bold tabular-nums ${stats.lowCents < stats.startCents ? 'text-red-400' : 'text-white/80'}`}>
            {formatDollars(stats.lowCents)}
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-dim mb-1">SNAPSHOTS</div>
          <div className="text-base font-bold tabular-nums text-terminal-dim">
            {chartData.length}
          </div>
        </div>
      </div>
    </div>
  );
}
