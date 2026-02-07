'use client';

import { useEffect, useState } from 'react';
import {
  RadialBarChart,
  RadialBar,
  ResponsiveContainer,
  PolarAngleAxis,
} from 'recharts';

interface WinRateGaugeProps {
  winRate?: number;
  totalTrades?: number;
  wins?: number;
  losses?: number;
}

export default function WinRateGauge({
  winRate = 0,
  totalTrades = 0,
  wins = 0,
  losses = 0
}: WinRateGaugeProps) {
  const [animatedRate, setAnimatedRate] = useState(0);

  useEffect(() => {
    // Animate the gauge
    const timer = setTimeout(() => {
      setAnimatedRate(winRate);
    }, 100);
    return () => clearTimeout(timer);
  }, [winRate]);

  // Use AMBER for great performance (60%+), GREEN for OK, RED for poor
  const data = [
    {
      name: 'Win Rate',
      value: animatedRate,
      fill: animatedRate >= 60 ? '#FFBF00' : animatedRate >= 40 ? '#00FF41' : '#FF0000',
    },
  ];

  const getWinRateClass = (rate: number) => {
    if (rate >= 60) return 'text-terminal-amber-bright amber-glow';
    if (rate >= 40) return 'text-terminal-green terminal-glow';
    return 'status-error';
  };

  return (
    <div className="border border-terminal-green p-4 h-full card-hover scan-hover transition-all duration-300 hover:shadow-terminal-glow-strong">
      {/* Header */}
      <div className="border-b border-terminal-green pb-2 mb-4 transition-all duration-300">
        <div className="text-xs text-terminal-dim mb-1">STATISTICS</div>
        <div className="text-lg font-bold terminal-glow tracking-wide transition-all duration-300 hover:terminal-glow-bright">
          WIN RATE
        </div>
      </div>

      {/* Gauge */}
      <div className="h-40 relative">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%"
            cy="50%"
            innerRadius="60%"
            outerRadius="90%"
            barSize={12}
            data={data}
            startAngle={180}
            endAngle={0}
          >
            <PolarAngleAxis
              type="number"
              domain={[0, 100]}
              angleAxisId={0}
              tick={false}
            />
            <RadialBar
              background={{ fill: '#33330020' }}
              dataKey="value"
              cornerRadius={6}
              style={{
                filter: animatedRate >= 60
                  ? 'drop-shadow(0 0 8px #FFD700) drop-shadow(0 0 12px rgba(255, 215, 0, 0.6))'
                  : animatedRate >= 40
                    ? 'drop-shadow(0 0 6px #00FF41) drop-shadow(0 0 10px rgba(0, 255, 65, 0.5))'
                    : 'drop-shadow(0 0 6px #FF0000) drop-shadow(0 0 10px rgba(255, 0, 0, 0.6))',
              }}
            />
          </RadialBarChart>
        </ResponsiveContainer>

        {/* Center text */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className={`text-5xl font-bold tabular-nums ${getWinRateClass(winRate)}`}>
            {winRate.toFixed(0)}%
          </div>
          <div className="text-sm text-terminal-dim mt-2 tracking-widest">WIN RATE</div>
        </div>
      </div>

      {/* Stats - Cyan for meta, Amber for wins, Red for losses */}
      <div className="border-t border-terminal-green mt-3 pt-4 grid grid-cols-3 gap-4 text-center">
        <div className="data-hover hover:bg-terminal-green hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200">
          <div className="text-sm text-terminal-cyan-dim tracking-wider mb-2">TOTAL</div>
          <div className="text-2xl font-bold text-terminal-cyan cyan-glow tabular-nums">
            {totalTrades}
          </div>
        </div>
        <div className="data-hover hover:bg-terminal-green hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200">
          <div className="text-sm text-terminal-amber-dim tracking-wider mb-2">WINS</div>
          <div className="text-2xl font-bold text-terminal-amber-bright amber-glow tabular-nums">
            {wins}
          </div>
        </div>
        <div className="data-hover hover:bg-terminal-green hover:bg-opacity-5 p-2 -m-2 rounded transition-all duration-200">
          <div className="text-sm text-terminal-red-dim tracking-wider mb-2">LOSSES</div>
          <div className={`text-2xl font-bold tabular-nums ${losses > 0 ? 'text-terminal-red-bright status-error' : 'text-terminal-green terminal-glow'}`}>
            {losses}
          </div>
        </div>
      </div>
    </div>
  );
}
