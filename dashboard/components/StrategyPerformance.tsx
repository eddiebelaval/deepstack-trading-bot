'use client';

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

interface StrategyData {
  name: string;
  trades: number;
  winRate: number;
  pnl: number;
}

interface StrategyPerformanceProps {
  data?: StrategyData[];
}

const CustomTooltip = ({ active, payload }: {active?: boolean; payload?: Array<{payload: StrategyData}>}) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="bg-terminal-bg-panel border border-terminal-amber/50 p-2 text-xs font-mono rounded">
        <div className="text-terminal-green-bright font-bold mb-1">{data.name}</div>
        <div className="text-terminal-cyan-dim">Trades: <span className="text-terminal-cyan">{data.trades}</span></div>
        <div className="text-terminal-cyan-dim">Win Rate: <span className="text-terminal-cyan">{data.winRate}%</span></div>
        <div className="text-terminal-amber-dim">
          P&L: <span className={data.pnl >= 0 ? 'text-terminal-amber-bright' : 'text-terminal-red-bright'}>
            {data.pnl >= 0 ? '+' : ''}{data.pnl}c
          </span>
        </div>
      </div>
    );
  }
  return null;
};

export default function StrategyPerformance({ data }: StrategyPerformanceProps) {
  const chartData = data || [];

  return (
    <div className="border border-terminal-green p-4 h-full card-hover scan-hover transition-all duration-300 hover:shadow-terminal-glow-strong">
      {/* Header */}
      <div className="border-b border-terminal-green pb-2 mb-4 transition-all duration-300">
        <div className="text-xs text-terminal-dim mb-1">ANALYTICS</div>
        <div className="text-lg font-bold terminal-glow tracking-wide transition-all duration-300 hover:terminal-glow-bright">
          STRATEGY P&L
        </div>
      </div>

      {chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center">
          <div className="text-center">
            <div className="text-terminal-dim/40 text-sm mb-2">NO STRATEGY DATA</div>
            <div className="text-terminal-dim/30 text-xs">Strategy performance will appear after trades execute</div>
          </div>
        </div>
      ) : (
        <>
          {/* Chart */}
          <div className="h-48 chart-glow animate-glow-pulse">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="#00550040"
                  vertical={false}
                />
                <XAxis
                  dataKey="name"
                  tick={{ fill: '#00AA2B', fontSize: 11 }}
                  axisLine={{ stroke: '#00550060' }}
                  tickLine={{ stroke: '#00550060' }}
                />
                <YAxis
                  tick={{ fill: '#00AA2B', fontSize: 12 }}
                  axisLine={{ stroke: '#00550060' }}
                  tickLine={{ stroke: '#00550060' }}
                  tickFormatter={(value) => `${value}c`}
                />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: '#00550020' }} />
                <Bar
                  dataKey="pnl"
                  radius={[3, 3, 0, 0]}
                  style={{
                    filter: 'drop-shadow(0 0 4px #FFBF00) drop-shadow(0 0 8px rgba(255, 191, 0, 0.5))',
                  }}
                >
                  {chartData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.pnl >= 0 ? '#FFD700' : '#FF3333'}
                      fillOpacity={0.9}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Legend - Cyan for win rates */}
          <div className="border-t border-terminal-green mt-4 pt-4 grid grid-cols-4 gap-3 text-xs">
            {chartData.map((strategy) => (
              <div key={strategy.name} className="text-center data-hover hover:bg-terminal-green hover:bg-opacity-5 px-1 py-2 -mx-1 rounded transition-all duration-200">
                <div className="text-terminal-cyan-dim truncate tracking-wider mb-1.5">{strategy.name}</div>
                <div className="text-terminal-cyan cyan-glow text-base font-bold">{strategy.winRate}%</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
