'use client';

import { Strategy } from '@/lib/types';
import { getStrategyMeta } from '@/lib/strategy-meta';

interface StrategyCardProps {
  strategy: Strategy;
  onClick?: () => void;
}

export default function StrategyCard({ strategy, onClick }: StrategyCardProps) {
  const meta = getStrategyMeta(strategy.name);

  const statusSymbol = () => {
    switch (strategy.status) {
      case 'active':
        return '[ACTIVE]';
      case 'scanning':
        return '[SCAN..]';
      case 'inactive':
        return '[-----]';
      case 'error':
        return '[ERROR]';
      default:
        return '[-----]';
    }
  };

  const statusClass = () => {
    switch (strategy.status) {
      case 'active':
        return 'status-active terminal-glow';
      case 'scanning':
        return 'status-active animate-blink';
      case 'inactive':
        return 'status-inactive';
      case 'error':
        return 'status-error';
      default:
        return 'status-inactive';
    }
  };

  return (
    <button
      onClick={onClick}
      className="panel p-2 md:p-4 flex flex-col h-full text-left w-full cursor-pointer group overflow-hidden"
    >
      {/* Header */}
      <div className="border-b border-terminal-green/30 pb-2 mb-2 md:mb-3 w-full">
        <div className="flex justify-between items-center">
          <div className="text-[9px] md:text-xs text-terminal-dim mb-1">STRATEGY</div>
          <div className="text-[9px] md:text-xs text-terminal-dim group-hover:text-terminal-green transition-colors">[+]</div>
        </div>
        <div className="text-xs md:text-lg font-bold terminal-glow tracking-wide uppercase transition-all duration-300 group-hover:terminal-glow-bright truncate">
          {meta.shortName}
        </div>
        <div className="text-[8px] md:text-[10px] text-terminal-amber/60 mt-0.5 tracking-wider">
          {meta.edgeType.toUpperCase()}
        </div>
      </div>

      {/* Status */}
      <div className="flex justify-between items-center mb-2 md:mb-4">
        <span className="text-[9px] md:text-xs text-terminal-dim tracking-wider">STATUS</span>
        <span className={`text-[10px] md:text-sm font-bold tracking-wide ${statusClass()}`}>
          {statusSymbol()}
        </span>
      </div>

      {/* Metrics */}
      <div className="space-y-2 md:space-y-4 flex-grow">
        {strategy.blended_win_rate !== null && strategy.blended_win_rate !== undefined && (
          <div className="flex justify-between items-center md:hover:bg-terminal-green md:hover:bg-opacity-5 md:px-2 md:-mx-2 py-1 md:py-2 transition-all duration-200 rounded">
            <span className="text-[9px] md:text-sm text-terminal-dim tracking-wider">W/R:</span>
            <div className="flex items-center gap-1.5">
              <span className="text-sm md:text-lg font-mono tabular-nums terminal-glow transition-all duration-300">
                {(strategy.blended_win_rate * 100).toFixed(1)}%
              </span>
              {strategy.health_status && strategy.health_status !== 'unknown' && (
                <span className={`text-[8px] md:text-[10px] font-mono px-1 py-0.5 rounded ${
                  strategy.health_status === 'healthy' ? 'text-terminal-green bg-terminal-green/10' :
                  strategy.health_status === 'warning' ? 'text-terminal-amber bg-terminal-amber/10' :
                  'text-terminal-red bg-terminal-red/10'
                }`}>
                  {strategy.blended_ev_cents !== null && strategy.blended_ev_cents !== undefined
                    ? `${strategy.blended_ev_cents >= 0 ? '+' : ''}${strategy.blended_ev_cents.toFixed(1)}c`
                    : strategy.health_status.toUpperCase()}
                </span>
              )}
            </div>
          </div>
        )}

        <div className="flex justify-between items-center md:hover:bg-terminal-green md:hover:bg-opacity-5 md:px-2 md:-mx-2 py-1 md:py-2 transition-all duration-200 rounded">
          <span className="text-[9px] md:text-sm text-terminal-dim tracking-wider">POS:</span>
          <span className="text-sm md:text-lg font-mono tabular-nums terminal-glow transition-all duration-300">
            {strategy.active_positions.toString().padStart(3, '0')}
          </span>
        </div>

        <div className="flex justify-between items-center md:hover:bg-terminal-amber md:hover:bg-opacity-5 md:px-2 md:-mx-2 py-1 md:py-2 transition-all duration-200 rounded">
          <span className="text-[9px] md:text-sm text-terminal-amber-dim tracking-wider">OPPS:</span>
          <span className="text-sm md:text-lg font-mono tabular-nums text-terminal-amber amber-glow transition-all duration-300">
            {strategy.opportunities_found.toString().padStart(3, '0')}
          </span>
        </div>
      </div>

      {/* Last scan - CYAN for timestamps */}
      <div className="mt-2 md:mt-4 pt-2 md:pt-3 border-t border-terminal-green transition-all duration-300 w-full">
        <div className="text-[9px] md:text-sm text-terminal-cyan-dim tracking-wider mb-1 md:mb-2">LAST SCAN</div>
        <div className="text-[10px] md:text-sm font-mono text-terminal-cyan truncate">
          {strategy.last_scan || 'NO DATA'}
        </div>
      </div>
    </button>
  );
}
