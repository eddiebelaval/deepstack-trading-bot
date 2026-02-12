'use client';

import { Strategy } from '@/lib/types';
import { getStrategyMeta } from '@/lib/strategy-meta';
import Sparkline from '@/components/Sparkline';

interface StrategyRowProps {
  strategy: Strategy;
  sparklineData?: number[];
  onClick?: () => void;
}

export default function StrategyRow({ strategy, sparklineData, onClick }: StrategyRowProps) {
  const meta = getStrategyMeta(strategy.name);

  const statusDot = () => {
    switch (strategy.status) {
      case 'active':
        return 'bg-terminal-green';
      case 'scanning':
        return 'bg-terminal-green animate-blink';
      case 'inactive':
        return 'bg-terminal-dim';
      case 'error':
        return 'bg-terminal-red';
      default:
        return 'bg-terminal-dim';
    }
  };

  const winRateDisplay = strategy.blended_win_rate !== null && strategy.blended_win_rate !== undefined
    ? `${(strategy.blended_win_rate * 100).toFixed(0)}%`
    : '--';

  const winRateColor = () => {
    if (strategy.blended_win_rate === null || strategy.blended_win_rate === undefined) return 'text-terminal-dim';
    if (strategy.blended_win_rate >= 0.6) return 'text-terminal-green';
    if (strategy.blended_win_rate >= 0.5) return 'text-terminal-amber';
    return 'text-terminal-red';
  };

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-terminal-green/5 transition-colors group"
    >
      {/* Status dot */}
      <span className={`w-2 h-2 rounded-full shrink-0 ${statusDot()}`} />

      {/* Short name */}
      <span className="text-xs font-mono text-terminal-green tracking-wider w-[100px] truncate shrink-0">
        {meta.shortName}
      </span>

      {/* Sparkline */}
      <span className="hidden md:inline-block w-[80px] shrink-0">
        {sparklineData && sparklineData.length >= 2 ? (
          <Sparkline data={sparklineData} width={80} height={16} showDot={false} />
        ) : (
          <span className="text-[9px] text-terminal-dim">--</span>
        )}
      </span>

      {/* Win rate */}
      <span className={`text-xs font-mono tabular-nums w-[40px] text-right shrink-0 ${winRateColor()}`}>
        {winRateDisplay}
      </span>

      {/* Positions */}
      <span className="text-xs font-mono tabular-nums text-terminal-cyan w-[24px] text-right shrink-0">
        {strategy.active_positions}
      </span>

      {/* Expand indicator */}
      <span className="text-[10px] text-terminal-dim group-hover:text-terminal-green ml-auto transition-colors">
        [+]
      </span>
    </button>
  );
}
