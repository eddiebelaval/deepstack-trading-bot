'use client';

import { Settlement } from '@/lib/types';

interface SettlementsHistoryProps {
  settlements: Settlement[];
}

export default function SettlementsHistory({ settlements }: SettlementsHistoryProps) {
  const formatTime = (timestamp: string | null) => {
    if (!timestamp) return '---';
    const d = new Date(timestamp);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) +
      ' ' +
      d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
  };

  const formatCents = (cents: number) => {
    const dollars = Math.abs(cents) / 100;
    const prefix = cents < 0 ? '-' : cents > 0 ? '+' : '';
    return `${prefix}$${dollars.toFixed(2)}`;
  };

  const resultColor = (result: string) => {
    switch (result) {
      case 'yes':
      case 'all_yes':
        return 'text-terminal-green';
      case 'no':
      case 'all_no':
        return 'text-terminal-red-bright';
      case 'void':
        return 'text-terminal-amber';
      default:
        return 'text-terminal-dim';
    }
  };

  const pnlColor = (pnl: number | null) => {
    if (pnl === null) return 'text-terminal-dim';
    if (pnl > 0) return 'text-terminal-green';
    if (pnl < 0) return 'text-terminal-red-bright';
    return 'text-terminal-dim';
  };

  // Aggregate stats
  const totalRevenue = settlements.reduce((sum, s) => sum + s.revenue, 0);
  const totalCost = settlements.reduce((sum, s) => sum + s.yes_total_cost + s.no_total_cost, 0);
  const totalPnl = totalRevenue - totalCost;
  const wins = settlements.filter(s => (s.net_pnl_cents ?? 0) > 0).length;
  const losses = settlements.filter(s => (s.net_pnl_cents ?? 0) < 0).length;

  if (settlements.length === 0) {
    return (
      <div className="panel p-4">
        <div className="border-b border-terminal-green pb-2 mb-4">
          <div className="text-xs text-terminal-dim mb-1">RESOLVED MARKETS</div>
          <div className="text-lg font-bold terminal-glow tracking-wide">SETTLEMENTS</div>
        </div>
        <div className="text-center py-8 text-terminal-dim">NO SETTLEMENTS RECORDED</div>
      </div>
    );
  }

  return (
    <div className="panel p-4">
      <div className="border-b border-terminal-green pb-2 mb-4">
        <div className="text-xs text-terminal-dim mb-1">RESOLVED MARKETS</div>
        <div className="flex justify-between items-baseline">
          <div className="text-lg font-bold terminal-glow tracking-wide">SETTLEMENTS</div>
          <div className="text-xs text-terminal-dim">{settlements.length} RESOLVED</div>
        </div>
      </div>

      {/* Summary Bar */}
      <div className="grid grid-cols-4 gap-2 mb-4 text-xs font-mono">
        <div className="text-center">
          <div className="text-terminal-dim">NET P&L</div>
          <div className={`font-bold ${pnlColor(totalPnl)}`}>{formatCents(totalPnl)}</div>
        </div>
        <div className="text-center">
          <div className="text-terminal-dim">REVENUE</div>
          <div className="text-terminal-green">{formatCents(totalRevenue)}</div>
        </div>
        <div className="text-center">
          <div className="text-terminal-dim">WINS</div>
          <div className="text-terminal-green">{wins}</div>
        </div>
        <div className="text-center">
          <div className="text-terminal-dim">LOSSES</div>
          <div className="text-terminal-red-bright">{losses}</div>
        </div>
      </div>

      {/* Mobile Card View */}
      <div className="md:hidden space-y-2">
        {settlements.map((s) => (
          <div key={s.ticker} className="border border-terminal-green/30 rounded p-3 space-y-1">
            <div className="flex justify-between items-start">
              <span className="text-sm text-terminal-green font-mono truncate max-w-[65%]">{s.ticker}</span>
              <span className={`text-xs font-bold uppercase ${resultColor(s.market_result)}`}>
                {s.market_result.toUpperCase()}
              </span>
            </div>
            <div className="flex justify-between text-[10px] text-terminal-dim">
              <span>YES: {s.yes_count} @ {formatCents(s.yes_total_cost)}</span>
              <span>NO: {s.no_count} @ {formatCents(s.no_total_cost)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className={`text-sm font-bold ${pnlColor(s.net_pnl_cents)}`}>
                {s.net_pnl_cents !== null ? formatCents(s.net_pnl_cents) : '---'}
              </span>
              <span className="text-[10px] text-terminal-dim">{formatTime(s.settled_time)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Desktop Table View */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-terminal-dim border-b border-terminal-green/20">
              <th className="text-left py-2 pr-3">SETTLED</th>
              <th className="text-left py-2 px-2">MARKET</th>
              <th className="text-center py-2 px-2">RESULT</th>
              <th className="text-right py-2 px-2">YES QTY</th>
              <th className="text-right py-2 px-2">NO QTY</th>
              <th className="text-right py-2 px-2">COST</th>
              <th className="text-right py-2 px-2">REVENUE</th>
              <th className="text-right py-2 px-2">NET P&L</th>
              <th className="text-right py-2 pl-2">FEE</th>
            </tr>
          </thead>
          <tbody>
            {settlements.map((s) => {
              const totalCostRow = s.yes_total_cost + s.no_total_cost;
              return (
                <tr key={s.ticker} className="border-b border-terminal-green/10 hover:bg-terminal-green/5 transition-colors">
                  <td className="py-2 pr-3 text-terminal-dim">{formatTime(s.settled_time)}</td>
                  <td className="py-2 px-2 text-terminal-green max-w-[200px] truncate" title={s.ticker}>
                    {s.ticker}
                  </td>
                  <td className={`py-2 px-2 text-center font-bold uppercase ${resultColor(s.market_result)}`}>
                    {s.market_result}
                  </td>
                  <td className="py-2 px-2 text-right">{s.yes_count || '---'}</td>
                  <td className="py-2 px-2 text-right">{s.no_count || '---'}</td>
                  <td className="py-2 px-2 text-right text-terminal-dim">{formatCents(totalCostRow)}</td>
                  <td className="py-2 px-2 text-right text-terminal-green">{formatCents(s.revenue)}</td>
                  <td className={`py-2 px-2 text-right font-bold ${pnlColor(s.net_pnl_cents)}`}>
                    {s.net_pnl_cents !== null ? formatCents(s.net_pnl_cents) : '---'}
                  </td>
                  <td className="py-2 pl-2 text-right text-terminal-dim">{s.fee_cost || '---'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
