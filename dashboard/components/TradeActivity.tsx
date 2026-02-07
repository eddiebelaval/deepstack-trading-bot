'use client';

import { useEffect, useState } from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface ActivityData {
  hour: string;
  trades: number;
  volume: number;
  opportunities: number;
}

interface TradeActivityProps {
  data?: ActivityData[];
  onOpportunitiesClick?: () => void;
}

// Generate mock data
function generateMockData(): ActivityData[] {
  const data: ActivityData[] = [];
  const now = new Date();

  for (let i = 11; i >= 0; i--) {
    const hour = new Date(now.getTime() - i * 60 * 60 * 1000);
    data.push({
      hour: hour.toLocaleTimeString('en-US', { hour: '2-digit' }),
      trades: Math.floor(Math.random() * 5),
      volume: Math.floor(Math.random() * 500) + 100,
      opportunities: Math.floor(Math.random() * 15) + 2,
    });
  }

  return data;
}

interface TooltipPayload {
  name: string;
  value: number;
}

const CustomTooltip = ({ active, payload, label }: {active?: boolean; payload?: TooltipPayload[]; label?: string}) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-terminal-black border border-terminal-green p-2 text-xs font-mono">
        <div className="text-terminal-green-bright font-bold mb-1">{label}</div>
        {payload.map((entry, index) => (
          <div key={index} className="text-terminal-dim">
            {entry.name}: <span className="text-terminal-green">{entry.value}</span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

export default function TradeActivity({ data, onOpportunitiesClick }: TradeActivityProps) {
  const [chartData, setChartData] = useState<ActivityData[]>([]);

  useEffect(() => {
    setChartData(data || generateMockData());
  }, [data]);

  const totalTrades = chartData.reduce((sum, d) => sum + d.trades, 0);
  const totalOpps = chartData.reduce((sum, d) => sum + d.opportunities, 0);

  return (
    <div className="border border-terminal-green p-4 h-full card-hover scan-hover transition-all duration-300 hover:shadow-terminal-glow-strong">
      {/* Header */}
      <div className="border-b border-terminal-green pb-2 mb-4 transition-all duration-300">
        <div className="text-xs text-terminal-dim mb-1">ACTIVITY</div>
        <div className="text-lg font-bold terminal-glow tracking-wide transition-all duration-300 hover:terminal-glow-bright">
          TRADES & SCANS (12H)
        </div>
      </div>

      {/* Chart */}
      <div className="h-48 chart-glow animate-glow-pulse">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#00550040"
              vertical={false}
            />
            <XAxis
              dataKey="hour"
              tick={{ fill: '#00AA2B', fontSize: 12 }}
              axisLine={{ stroke: '#00550060' }}
              tickLine={{ stroke: '#00550060' }}
            />
            <YAxis
              yAxisId="left"
              tick={{ fill: '#00AA2B', fontSize: 12 }}
              axisLine={{ stroke: '#00550060' }}
              tickLine={{ stroke: '#00550060' }}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fill: '#00AA2B', fontSize: 12 }}
              axisLine={{ stroke: '#00550060' }}
              tickLine={{ stroke: '#00550060' }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Bar
              yAxisId="left"
              dataKey="trades"
              fill="#00FF41"
              fillOpacity={0.7}
              radius={[3, 3, 0, 0]}
              name="Trades"
              style={{
                filter: 'drop-shadow(0 0 3px #00FF41)',
              }}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="opportunities"
              stroke="#FFBF00"
              strokeWidth={3}
              dot={false}
              name="Opportunities"
              style={{
                filter: 'drop-shadow(0 0 4px #FFBF00) drop-shadow(0 0 8px rgba(255, 191, 0, 0.5))',
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Stats */}
      <div className="border-t border-terminal-green mt-4 pt-4 grid grid-cols-3 gap-4 text-xs">
        <div className="data-hover hover:bg-terminal-green hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200">
          <div className="text-terminal-dim tracking-wider mb-2">TRADES</div>
          <div className="text-terminal-green-bright font-bold text-2xl terminal-glow tabular-nums">{totalTrades}</div>
        </div>
        <button
          onClick={onOpportunitiesClick}
          className="data-hover hover:bg-terminal-amber hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200 text-left cursor-pointer group"
        >
          <div className="text-terminal-amber-dim tracking-wider mb-2 group-hover:text-terminal-amber transition-colors">
            OPPS FOUND <span className="text-terminal-dim group-hover:text-terminal-amber">[+]</span>
          </div>
          <div className="text-terminal-amber font-bold text-2xl amber-glow tabular-nums">{totalOpps}</div>
        </button>
        <div className="data-hover hover:bg-terminal-green hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200">
          <div className="text-terminal-dim tracking-wider mb-2">EXEC RATE</div>
          <div className="text-terminal-green font-bold text-2xl terminal-glow tabular-nums">
            {totalOpps > 0 ? ((totalTrades / totalOpps) * 100).toFixed(0) : 0}%
          </div>
        </div>
      </div>
    </div>
  );
}
