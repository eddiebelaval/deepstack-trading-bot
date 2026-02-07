'use client';

import { useEffect, useState } from 'react';

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

  const getWinRateClass = (rate: number) => {
    if (rate >= 60) return 'text-terminal-amber-bright amber-glow';
    if (rate >= 40) return 'text-terminal-green terminal-glow';
    return 'status-error';
  };

  return (
    <div className="panel p-4 h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-terminal-green/30 pb-2 mb-3">
        <div className="text-xs text-terminal-dim mb-1">STATISTICS</div>
        <div className="text-base font-bold terminal-glow tracking-wide">
          WIN RATE
        </div>
      </div>

      {/* Main metric - big prominent number */}
      <div className="flex-1 flex flex-col items-center justify-center">
        <div className={`text-4xl font-bold tabular-nums ${getWinRateClass(winRate)}`}>
          {winRate.toFixed(0)}%
        </div>
        {/* Progress bar instead of radial gauge */}
        <div className="w-full mt-3 px-2">
          <div className="w-full h-2 bg-terminal-green/20 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${animatedRate}%`,
                backgroundColor: animatedRate >= 60 ? '#FFBF00' : animatedRate >= 40 ? '#00FF41' : '#FF0000',
                boxShadow: animatedRate >= 60
                  ? '0 0 8px #FFBF00'
                  : animatedRate >= 40
                    ? '0 0 6px #00FF41'
                    : '0 0 6px #FF0000',
              }}
            />
          </div>
          <div className="flex justify-between text-xs text-terminal-dim mt-1">
            <span>0%</span>
            <span>100%</span>
          </div>
        </div>
      </div>

      {/* Stats - compact row */}
      <div className="border-t border-terminal-green mt-3 pt-3 grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-xs text-terminal-cyan-dim tracking-wider mb-1">TOTAL</div>
          <div className="text-lg font-bold text-terminal-cyan tabular-nums">
            {totalTrades}
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-amber-dim tracking-wider mb-1">WINS</div>
          <div className="text-lg font-bold text-terminal-amber-bright tabular-nums">
            {wins}
          </div>
        </div>
        <div>
          <div className="text-xs text-terminal-red-dim tracking-wider mb-1">LOSSES</div>
          <div className={`text-lg font-bold tabular-nums ${losses > 0 ? 'text-terminal-red-bright' : 'text-terminal-green'}`}>
            {losses}
          </div>
        </div>
      </div>
    </div>
  );
}
