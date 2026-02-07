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
      <div className="bg-terminal-bg-panel border border-terminal-green/50 p-2 text-xs font-mono rounded">
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
    <div className="panel p-4 h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-terminal-green/30 pb-2 mb-3">
        <div className="text-xs text-terminal-dim mb-1">ACTIVITY</div>
        <div className="text-base font-bold terminal-glow tracking-wide">
          TRADES & SCANS
        </div>
      </div>

      {/* Chart - compact, no axis labels */}
      <div className="h-24 chart-glow">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#00550030"
              vertical={false}
            />
            <XAxis dataKey="hour" hide />
            <YAxis yAxisId="left" hide />
            <YAxis yAxisId="right" orientation="right" hide />
            <Tooltip content={<CustomTooltip />} />
            <Bar
              yAxisId="left"
              dataKey="trades"
              fill="#00FF41"
              fillOpacity={0.7}
              radius={[2, 2, 0, 0]}
              name="Trades"
              style={{ filter: 'drop-shadow(0 0 2px #00FF41)' }}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="opportunities"
              stroke="#FFBF00"
              strokeWidth={2}
              dot={false}
              name="Opportunities"
              style={{ filter: 'drop-shadow(0 0 3px #FFBF00)' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Stats - compact */}
      <div className="border-t border-terminal-green mt-2 pt-3 grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-xs text-terminal-dim tracking-wider mb-1">TRADES</div>
          <div className="text-lg font-bold text-terminal-green-bright tabular-nums">{totalTrades}</div>
        </div>
        <button
          onClick={onOpportunitiesClick}
          className="text-center cursor-pointer group"
        >
          <div className="text-xs text-terminal-amber-dim tracking-wider mb-1 group-hover:text-terminal-amber">
            OPPS [+]
          </div>
          <div className="text-lg font-bold text-terminal-amber tabular-nums">{totalOpps}</div>
        </button>
        <div>
          <div className="text-xs text-terminal-dim tracking-wider mb-1">EXEC</div>
          <div className="text-lg font-bold text-terminal-green tabular-nums">
            {totalOpps > 0 ? ((totalTrades / totalOpps) * 100).toFixed(0) : 0}%
          </div>
        </div>
      </div>
    </div>
  );
}
