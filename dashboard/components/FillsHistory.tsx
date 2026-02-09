'use client';

import { Fill } from '@/lib/types';

interface FillsHistoryProps {
  fills: Fill[];
}

export default function FillsHistory({ fills }: FillsHistoryProps) {
  const formatPrice = (cents: number | null) => {
    if (cents === null || cents === undefined) return '---';
    return `${cents}c`;
  };

  const formatTime = (timestamp: string | null) => {
    if (!timestamp) return '---';
    const d = new Date(timestamp);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) +
      ' ' +
      d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const getPrice = (fill: Fill) => fill.yes_price ?? fill.no_price;

  if (fills.length === 0) {
    return (
      <div className="panel p-4">
        <div className="border-b border-terminal-green pb-2 mb-4">
          <div className="text-xs text-terminal-dim mb-1">EXECUTION LOG</div>
          <div className="text-lg font-bold terminal-glow tracking-wide">FILLS</div>
        </div>
        <div className="text-center py-8 text-terminal-dim">NO FILLS RECORDED</div>
      </div>
    );
  }

  return (
    <div className="panel p-4">
      <div className="border-b border-terminal-green pb-2 mb-4">
        <div className="text-xs text-terminal-dim mb-1">EXECUTION LOG</div>
        <div className="flex justify-between items-baseline">
          <div className="text-lg font-bold terminal-glow tracking-wide">FILLS</div>
          <div className="text-xs text-terminal-dim">{fills.length} EXECUTIONS</div>
        </div>
      </div>

      {/* Mobile Card View */}
      <div className="md:hidden space-y-2">
        {fills.map((fill) => (
          <div key={fill.fill_id} className="border border-terminal-green/30 rounded p-3 space-y-1">
            <div className="flex justify-between items-start">
              <div>
                <span className={`text-xs font-bold ${fill.action === 'buy' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                  {fill.action.toUpperCase()}
                </span>
                <span className={`text-xs ml-1 ${fill.side === 'yes' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                  {fill.side.toUpperCase()}
                </span>
                <span className="text-xs text-terminal-dim ml-2">x{fill.count}</span>
              </div>
              <span className="text-xs text-terminal-dim">
                {fill.is_taker ? 'TAKER' : 'MAKER'}
              </span>
            </div>
            <div className="text-sm text-terminal-green font-mono truncate">{fill.ticker}</div>
            <div className="flex justify-between text-[10px] text-terminal-dim">
              <span>PRICE: {formatPrice(getPrice(fill))}</span>
              <span>FEE: {fill.fee_cost || '---'}</span>
              <span>{formatTime(fill.created_time)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Desktop Table View */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-terminal-dim border-b border-terminal-green/20">
              <th className="text-left py-2 pr-3">TIME</th>
              <th className="text-left py-2 px-2">MARKET</th>
              <th className="text-center py-2 px-2">ACTION</th>
              <th className="text-center py-2 px-2">SIDE</th>
              <th className="text-right py-2 px-2">QTY</th>
              <th className="text-right py-2 px-2">PRICE</th>
              <th className="text-center py-2 px-2">TYPE</th>
              <th className="text-right py-2 px-2">FEE</th>
              <th className="text-right py-2 pl-2">ORDER ID</th>
            </tr>
          </thead>
          <tbody>
            {fills.map((fill) => (
              <tr key={fill.fill_id} className="border-b border-terminal-green/10 hover:bg-terminal-green/5 transition-colors">
                <td className="py-2 pr-3 text-terminal-dim">{formatTime(fill.created_time)}</td>
                <td className="py-2 px-2 text-terminal-green max-w-[180px] truncate" title={fill.ticker}>
                  {fill.ticker}
                </td>
                <td className={`py-2 px-2 text-center font-bold ${fill.action === 'buy' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                  {fill.action.toUpperCase()}
                </td>
                <td className={`py-2 px-2 text-center ${fill.side === 'yes' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                  {fill.side.toUpperCase()}
                </td>
                <td className="py-2 px-2 text-right">{fill.count}</td>
                <td className="py-2 px-2 text-right">{formatPrice(getPrice(fill))}</td>
                <td className="py-2 px-2 text-center text-terminal-dim">
                  {fill.is_taker ? 'TAKER' : 'MAKER'}
                </td>
                <td className="py-2 px-2 text-right text-terminal-dim">{fill.fee_cost || '---'}</td>
                <td className="py-2 pl-2 text-right text-terminal-dim max-w-[80px] truncate" title={fill.order_id || ''}>
                  {fill.order_id ? fill.order_id.slice(-8) : '---'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
