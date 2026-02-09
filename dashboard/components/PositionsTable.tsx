'use client';

import { Position } from '@/lib/types';

interface PositionsTableProps {
  positions: Position[];
}

export default function PositionsTable({ positions }: PositionsTableProps) {
  const formatCents = (cents: number | null) => {
    if (cents === null || cents === undefined) return '---';
    return `$${(cents / 100).toFixed(2)}`;
  };

  const formatPrice = (cents: number | null) => {
    if (cents === null || cents === undefined) return '---';
    return `${cents}c`;
  };

  const computeUnrealizedPnl = (pos: Position): number | null => {
    if (pos.current_price === null || pos.market_value_cents === null || pos.market_exposure === 0) {
      return null;
    }
    return pos.market_value_cents - pos.market_exposure;
  };

  const getPnlClass = (pnl: number | null) => {
    if (pnl === null) return 'text-terminal-dim';
    if (pnl > 0) return 'text-terminal-amber-bright amber-glow';
    if (pnl < 0) return 'text-terminal-red-bright';
    return 'text-terminal-green';
  };

  if (positions.length === 0) {
    return (
      <div className="panel p-4">
        <div className="border-b border-terminal-green pb-2 mb-4">
          <div className="text-xs text-terminal-dim mb-1">PORTFOLIO</div>
          <div className="text-lg font-bold terminal-glow tracking-wide">OPEN POSITIONS</div>
        </div>
        <div className="text-center py-8 text-terminal-dim">NO OPEN POSITIONS</div>
      </div>
    );
  }

  return (
    <div className="panel p-4">
      <div className="border-b border-terminal-green pb-2 mb-4">
        <div className="text-xs text-terminal-dim mb-1">PORTFOLIO</div>
        <div className="flex justify-between items-baseline">
          <div className="text-lg font-bold terminal-glow tracking-wide">OPEN POSITIONS</div>
          <div className="text-xs text-terminal-dim">{positions.length} ACTIVE</div>
        </div>
      </div>

      {/* Mobile Card View */}
      <div className="md:hidden space-y-2">
        {positions.map((pos) => {
          const unrealizedPnl = computeUnrealizedPnl(pos);
          return (
            <div key={pos.ticker} className="border border-terminal-green/30 rounded p-3 space-y-1">
              <div className="flex justify-between items-start">
                <div>
                  <span className={`text-xs font-bold ${pos.side === 'yes' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                    {pos.side.toUpperCase()}
                  </span>
                  <span className="text-xs text-terminal-dim ml-2">{pos.contracts} contracts</span>
                </div>
                <span className={`text-xs font-mono ${getPnlClass(unrealizedPnl)}`}>
                  {unrealizedPnl !== null ? `${unrealizedPnl >= 0 ? '+' : ''}${formatCents(unrealizedPnl)}` : '---'}
                </span>
              </div>
              <div className="text-sm text-terminal-green font-mono truncate">{pos.market_title || pos.ticker}</div>
              <div className="flex justify-between text-[10px] text-terminal-dim">
                <span>PRICE: {formatPrice(pos.current_price)}</span>
                <span>VALUE: {formatCents(pos.market_value_cents)}</span>
                <span>EXPOSURE: {formatCents(pos.market_exposure)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop Table View */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-terminal-dim border-b border-terminal-green/20">
              <th className="text-left py-2 pr-3">MARKET</th>
              <th className="text-center py-2 px-2">SIDE</th>
              <th className="text-right py-2 px-2">QTY</th>
              <th className="text-right py-2 px-2">PRICE</th>
              <th className="text-right py-2 px-2">AVG ENTRY</th>
              <th className="text-right py-2 px-2">VALUE</th>
              <th className="text-right py-2 px-2">EXPOSURE</th>
              <th className="text-right py-2 px-2">UNREAL P&L</th>
              <th className="text-right py-2 px-2">REAL P&L</th>
              <th className="text-right py-2 pl-2">FEES</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const unrealizedPnl = computeUnrealizedPnl(pos);
              return (
                <tr key={pos.ticker} className="border-b border-terminal-green/10 hover:bg-terminal-green/5 transition-colors">
                  <td className="py-2 pr-3 text-terminal-green max-w-[200px] truncate" title={pos.market_title || pos.ticker}>
                    {pos.market_title || pos.ticker}
                  </td>
                  <td className={`py-2 px-2 text-center font-bold ${pos.side === 'yes' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                    {pos.side.toUpperCase()}
                  </td>
                  <td className="py-2 px-2 text-right">{pos.contracts}</td>
                  <td className="py-2 px-2 text-right">{formatPrice(pos.current_price)}</td>
                  <td className="py-2 px-2 text-right">{pos.avg_entry_price_cents ? formatPrice(pos.avg_entry_price_cents) : '---'}</td>
                  <td className="py-2 px-2 text-right">{formatCents(pos.market_value_cents)}</td>
                  <td className="py-2 px-2 text-right">{formatCents(pos.market_exposure)}</td>
                  <td className={`py-2 px-2 text-right ${getPnlClass(unrealizedPnl)}`}>
                    {unrealizedPnl !== null ? `${unrealizedPnl >= 0 ? '+' : ''}${formatCents(unrealizedPnl)}` : '---'}
                  </td>
                  <td className={`py-2 px-2 text-right ${getPnlClass(pos.realized_pnl)}`}>
                    {formatCents(pos.realized_pnl)}
                  </td>
                  <td className="py-2 pl-2 text-right text-terminal-dim">{formatCents(pos.fees_paid)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
