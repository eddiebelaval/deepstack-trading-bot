'use client';

import { useEffect, useState, useMemo } from 'react';
import {
  AreaChart,
  Area,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';

interface DataPoint {
  timestamp: string;
  value: number;
  label: string;
}

interface PerformanceSparklineProps {
  data?: DataPoint[];
}

// Generate mock historical data
function generateMockData(): DataPoint[] {
  const data: DataPoint[] = [];
  const now = new Date();
  const points = 24; // Last 24 hours
  const intervalMs = 60 * 60 * 1000; // 1 hour

  let runningPnl = 0;
  const volatility = 2;
  const trend = Math.random() > 0.4 ? 0.3 : -0.2;

  for (let i = points - 1; i >= 0; i--) {
    const timestamp = new Date(now.getTime() - i * intervalMs);
    const change = (Math.random() - 0.5) * volatility + trend;
    runningPnl += change;

    data.push({
      timestamp: timestamp.toISOString(),
      value: Math.round(runningPnl * 100) / 100,
      label: timestamp.toLocaleTimeString('en-US', { hour: '2-digit' }),
    });
  }

  return data;
}

export default function PerformanceSparkline({ data }: PerformanceSparklineProps) {
  const [chartData, setChartData] = useState<DataPoint[]>([]);

  useEffect(() => {
    setChartData(data || generateMockData());
  }, [data]);

  const stats = useMemo(() => {
    if (chartData.length === 0) return { current: 0, start: 0, change: 0, isProfit: true };

    const values = chartData.map(d => d.value);
    const current = values[values.length - 1] || 0;
    const start = values[0] || 0;
    const change = current - start;
    const isProfit = current >= start;

    return { current, start, change, isProfit };
  }, [chartData]);

  const color = stats.isProfit ? '#22c55e' : '#ef4444';
  const colorDim = stats.isProfit ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)';

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ value: number; payload: DataPoint }> }) => {
    if (active && payload && payload.length) {
      const value = payload[0].value;
      const label = payload[0].payload.label;
      return (
        <div className="bg-terminal-bg-panel border border-white/10 rounded px-2 py-1 text-xs font-mono">
          <div className="text-terminal-dim">{label}</div>
          <div style={{ color }}>{value >= 0 ? '+' : ''}{value.toFixed(2)}%</div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="panel p-4 h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-terminal-green/30 pb-2 mb-3">
        <div className="text-xs text-terminal-dim mb-1">PERFORMANCE</div>
        <div className="text-base font-bold terminal-glow tracking-wide">
          24H RETURN
        </div>
      </div>

      {/* Main metric */}
      <div className="flex items-center justify-between mb-2">
        <span
          className="text-3xl font-bold tabular-nums"
          style={{ color, textShadow: `0 0 12px ${colorDim}` }}
        >
          {stats.current >= 0 ? '+' : ''}{stats.current.toFixed(2)}%
        </span>
        <span
          className="text-sm font-medium"
          style={{ color: stats.isProfit ? 'rgba(34, 197, 94, 0.7)' : 'rgba(239, 68, 68, 0.7)' }}
        >
          {stats.change >= 0 ? '+' : ''}{stats.change.toFixed(2)}%
        </span>
      </div>

      {/* Sparkline */}
      <div className="flex-1 min-h-[60px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="sparklineGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              fill="url(#sparklineGradient)"
              dot={false}
              style={{ filter: `drop-shadow(0 0 4px ${colorDim})` }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Stats row */}
      <div className="border-t border-terminal-green/30 mt-2 pt-2 grid grid-cols-2 gap-2 text-center">
        <div>
          <div className="text-xs text-terminal-dim tracking-wider">START</div>
          <div className="text-sm font-bold tabular-nums text-white/70">
            {stats.start >= 0 ? '+' : ''}{stats.start.toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-dim tracking-wider">NOW</div>
          <div className="text-sm font-bold tabular-nums" style={{ color }}>
            {stats.current >= 0 ? '+' : ''}{stats.current.toFixed(2)}%
          </div>
        </div>
      </div>
    </div>
  );
}
