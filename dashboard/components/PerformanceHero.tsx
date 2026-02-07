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

type TimeFrame = '1D' | '1W' | '1M' | '3M' | '1Y' | 'ALL';

interface DataPoint {
  timestamp: string;
  value: number;
  label: string;
}

interface PerformanceHeroProps {
  data?: DataPoint[];
}

// Colors matching Robinhood/DeepStack style
const COLORS = {
  profit: {
    line: '#22c55e',
    glow: 'rgba(34, 197, 94, 0.5)',
  },
  loss: {
    line: '#ef4444',
    glow: 'rgba(239, 68, 68, 0.5)',
  },
};

export default function PerformanceHero({ data }: PerformanceHeroProps) {
  const [timeframe, setTimeframe] = useState<TimeFrame>('1M');
  const chartData = data || [];

  // Calculate stats - Robinhood style: compare END vs START
  const stats = useMemo(() => {
    if (chartData.length === 0) return { current: 0, start: 0, high: 0, low: 0, change: 0, isProfit: true };

    const values = chartData.map(d => d.value);
    const current = values[values.length - 1] || 0;
    const start = values[0] || 0;
    const high = Math.max(...values);
    const low = Math.min(...values);
    const change = current - start;
    const isProfit = current >= start;

    return { current, start, high, low, change, isProfit };
  }, [chartData]);

  // Get colors based on profit/loss for the period
  const colors = stats.isProfit ? COLORS.profit : COLORS.loss;

  const timeframes: TimeFrame[] = ['1D', '1W', '1M', '3M', '1Y', 'ALL'];

  // Custom tooltip
  const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) => {
    if (active && payload && payload.length) {
      const value = payload[0].value;
      const fromStart = value - stats.start;
      const isUp = fromStart >= 0;
      return (
        <div className="bg-terminal-bg-panel/95 backdrop-blur border border-white/10 rounded-lg p-3 text-xs font-mono shadow-xl">
          <div className="text-terminal-dim mb-2">{label}</div>
          <div className={`text-2xl font-bold ${isUp ? 'text-green-400' : 'text-red-400'}`}>
            {value >= 0 ? '+' : ''}{value.toFixed(2)}%
          </div>
          <div className={`text-sm mt-1 ${isUp ? 'text-green-400/70' : 'text-red-400/70'}`}>
            {isUp ? '+' : ''}{fromStart.toFixed(2)}% from start
          </div>
        </div>
      );
    }
    return null;
  };

  if (chartData.length === 0) {
    return (
      <div className="panel panel-hero p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-xs text-terminal-dim mb-1 tracking-wider">PORTFOLIO PERFORMANCE</div>
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
      {/* Header with timeframe selector */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-xs text-terminal-dim mb-1 tracking-wider">PORTFOLIO PERFORMANCE</div>
          <div className="flex items-baseline gap-4">
            <span className={`text-4xl font-bold tabular-nums ${stats.isProfit ? 'text-green-400' : 'text-red-400'}`}
              style={{ textShadow: `0 0 20px ${colors.glow}` }}>
              {stats.current >= 0 ? '+' : ''}{stats.current.toFixed(2)}%
            </span>
            <span className={`text-lg font-medium ${stats.isProfit ? 'text-green-400/70' : 'text-red-400/70'}`}>
              {stats.change >= 0 ? '+' : ''}{stats.change.toFixed(2)}% this period
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
              tickFormatter={(value) => `${value >= 0 ? '+' : ''}${value.toFixed(0)}%`}
              domain={['dataMin - 2', 'dataMax + 2']}
              width={50}
            />
            <Tooltip content={<CustomTooltip />} />

            {/* Zero reference line */}
            <ReferenceLine
              y={stats.start}
              stroke="rgba(255,255,255,0.2)"
              strokeDasharray="4 4"
            />

            {/* Main area - color based on profit/loss */}
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
      <div className="grid grid-cols-4 gap-3 mt-4 pt-4 border-t border-white/5">
        <div>
          <div className="text-xs text-terminal-dim mb-1">START</div>
          <div className="text-lg font-bold tabular-nums text-white/80">
            {stats.start >= 0 ? '+' : ''}{stats.start.toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-dim mb-1">HIGH</div>
          <div className="text-lg font-bold tabular-nums text-green-400">
            +{stats.high.toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-dim mb-1">LOW</div>
          <div className={`text-lg font-bold tabular-nums ${stats.low >= 0 ? 'text-white/80' : 'text-red-400'}`}>
            {stats.low >= 0 ? '+' : ''}{stats.low.toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-dim mb-1">DATA POINTS</div>
          <div className="text-lg font-bold tabular-nums text-terminal-cyan">
            {chartData.length}
          </div>
        </div>
      </div>
    </div>
  );
}
