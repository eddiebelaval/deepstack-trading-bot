'use client';

import { useMemo } from 'react';
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

interface PnLDataPoint {
  time: string;
  pnl: number;
  cumulative: number;
}

interface PnLChartProps {
  data?: PnLDataPoint[];
}

const CustomTooltip = ({ active, payload, label }: {active?: boolean; payload?: Array<{value: number}>; label?: string}) => {
  if (active && payload && payload.length) {
    const value = payload[0].value;
    return (
      <div className="bg-terminal-bg-panel border border-terminal-amber/50 p-2 text-xs rounded">
        <div className="text-terminal-cyan-dim">{label}</div>
        <div className={`font-bold ${value >= 0 ? 'text-terminal-amber-bright' : 'text-terminal-red-bright'}`}>
          {value >= 0 ? '+' : ''}{value}c
        </div>
      </div>
    );
  }
  return null;
};

export default function PnLChart({ data }: PnLChartProps) {
  const chartData = data || [];

  const { minValue, maxValue, currentValue, domain } = useMemo(() => {
    const min = chartData.length > 0 ? Math.min(...chartData.map(d => d.cumulative)) : 0;
    const max = chartData.length > 0 ? Math.max(...chartData.map(d => d.cumulative)) : 0;
    const current = chartData[chartData.length - 1]?.cumulative ?? 0;
    return { minValue: min, maxValue: max, currentValue: current, domain: [Math.min(min - 5, -10), Math.max(max + 5, 10)] };
  }, [chartData]);

  return (
    <div className="panel p-4 h-full">
      {/* Header */}
      <div className="border-b border-terminal-green pb-2 mb-4 transition-all duration-300">
        <div className="text-xs text-terminal-dim mb-1">PERFORMANCE</div>
        <div className="text-lg font-bold terminal-glow tracking-wide transition-all duration-300 hover:terminal-glow-bright">
          P&L OVER TIME (24H)
        </div>
      </div>

      {chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center">
          <div className="text-terminal-dim/40 text-sm">NO P&L DATA</div>
        </div>
      ) : (
        <>
          <div className="h-48 chart-glow animate-glow-pulse">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                <defs>
                  <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00FF41" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#00FF41" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="#00550030"
                  vertical={false}
                />
                <XAxis
                  dataKey="time"
                  tick={{ fill: '#00AA2B', fontSize: 12 }}
                  axisLine={{ stroke: '#00550050' }}
                  tickLine={{ stroke: '#00550050' }}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fill: '#00AA2B', fontSize: 12 }}
                  axisLine={{ stroke: '#00550050' }}
                  tickLine={{ stroke: '#00550050' }}
                  domain={domain}
                  tickFormatter={(value) => `${value}c`}
                />
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine y={0} stroke="#00FF4180" strokeDasharray="3 3" />
                <Area
                  type="monotone"
                  dataKey="cumulative"
                  stroke="#00FF41"
                  strokeWidth={3}
                  fill="url(#pnlGradient)"
                  dot={false}
                  activeDot={{
                    r: 5,
                    fill: '#00FF41',
                    stroke: '#0D0208',
                    strokeWidth: 2,
                    style: {
                      filter: 'drop-shadow(0 0 6px #00FF41)',
                    },
                  }}
                  style={{
                    filter: 'drop-shadow(0 0 6px #00FF41)',
                  }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Footer stats - AMBER for money data, quick glance */}
          <div className="border-t border-terminal-green mt-4 pt-4 grid grid-cols-3 gap-4 text-xs">
            <div className="hover:bg-terminal-amber hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200">
              <div className="text-terminal-cyan-dim tracking-wider mb-1.5">HIGH</div>
              <div className="text-terminal-amber-bright font-bold amber-glow text-base">+{maxValue}c</div>
            </div>
            <div className="hover:bg-terminal-red hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200">
              <div className="text-terminal-cyan-dim tracking-wider mb-1.5">LOW</div>
              <div className={`font-bold text-base ${minValue < 0 ? 'text-terminal-red-bright' : 'text-terminal-amber'}`}>
                {minValue}c
              </div>
            </div>
            <div className="hover:bg-terminal-amber hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200">
              <div className="text-terminal-cyan-dim tracking-wider mb-1.5">CURRENT</div>
              <div className={`font-bold text-base ${currentValue >= 0 ? 'text-terminal-amber-bright amber-glow' : 'text-terminal-red-bright'}`}>
                {currentValue >= 0 ? '+' : ''}{currentValue}c
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
