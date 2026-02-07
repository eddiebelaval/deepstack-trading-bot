'use client';

import { Trade } from '@/lib/types';

interface TradeJournalProps {
  trades: Trade[];
  onTradeClick?: (trade: Trade) => void;
}

export default function TradeJournal({ trades, onTradeClick }: TradeJournalProps) {
  const formatCents = (cents: number | null) => {
    if (cents === null) return '---';
    return `$${(cents / 100).toFixed(2)}`;
  };

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  const getPnlClass = (pnl: number | null) => {
    if (pnl === null) return 'text-terminal-dim';
    if (pnl > 0) return 'text-terminal-amber-bright amber-glow';
    if (pnl < 0) return 'text-terminal-red-bright';
    return 'text-terminal-green';
  };

  const getStatusSymbol = (status: string) => {
    switch (status) {
      case 'open':
        return '[OPEN]';
      case 'closed':
        return '[DONE]';
      case 'pending':
        return '[WAIT]';
      case 'cancelled':
        return '[CANC]';
      default:
        return '[----]';
    }
  };

  return (
    <div className="panel p-4">
      {/* Header */}
      <div className="border-b border-terminal-green pb-2 mb-4">
        <div className="text-xs text-terminal-dim mb-1">TRADE JOURNAL</div>
        <div className="text-lg font-bold terminal-glow tracking-wide">
          RECENT TRADES
        </div>
      </div>

      {/* Mobile Card View */}
      <div className="md:hidden space-y-2">
        {trades.length === 0 ? (
          <div className="text-center py-8 text-terminal-dim text-base">
            NO TRADES YET <span className="cursor">_</span>
          </div>
        ) : (
          trades.slice(0, 10).map((trade) => (
            <div
              key={trade.id}
              onClick={() => onTradeClick?.(trade)}
              className="border border-terminal-green/30 p-3 rounded cursor-pointer hover:bg-terminal-green/5 transition-all"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="terminal-glow text-sm font-bold">{trade.market_ticker.substring(0, 12)}</span>
                <span className={`text-sm font-bold tabular-nums ${getPnlClass(trade.pnl_cents)}`}>
                  {formatCents(trade.pnl_cents)}
                </span>
              </div>
              <div className="flex items-center gap-3 text-[10px] text-terminal-dim">
                <span className="text-terminal-amber">{trade.strategy.substring(0, 8).toUpperCase()}</span>
                <span className="text-terminal-green">{trade.side === 'yes' ? 'YES' : 'NO'} x{trade.contracts}</span>
                <span className="text-terminal-cyan">{formatTime(trade.created_at)}</span>
                <span className="ml-auto text-terminal-cyan">{getStatusSymbol(trade.status)}</span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Desktop Table View */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full font-mono text-sm">
          <thead>
            <tr className="border-b-2 border-terminal-green">
              <th className="text-left py-4 px-3 text-terminal-cyan-dim font-normal tracking-wider text-xs">TIME</th>
              <th className="text-left py-4 px-3 text-terminal-green-dim font-normal tracking-wider text-xs">TICKER</th>
              <th className="text-left py-4 px-3 text-terminal-amber-dim font-normal tracking-wider text-xs">STRAT</th>
              <th className="text-left py-4 px-3 text-terminal-green-dim font-normal tracking-wider text-xs">SIDE</th>
              <th className="text-right py-4 px-3 text-terminal-green-dim font-normal tracking-wider text-xs">SIZE</th>
              <th className="text-right py-4 px-3 text-terminal-green-dim font-normal tracking-wider text-xs">ENTRY</th>
              <th className="text-right py-4 px-3 text-terminal-green-dim font-normal tracking-wider text-xs">EXIT</th>
              <th className="text-right py-4 px-3 text-terminal-amber-dim font-normal tracking-wider text-xs">P/L</th>
              <th className="text-left py-4 px-3 text-terminal-cyan-dim font-normal tracking-wider text-xs">STATUS</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={9} className="text-center py-8 text-terminal-dim text-base">
                  NO TRADES YET <span className="cursor">_</span>
                </td>
              </tr>
            ) : (
              trades.slice(0, 10).map((trade) => (
                <tr
                  key={trade.id}
                  onClick={() => onTradeClick?.(trade)}
                  className="border-b border-terminal-green border-opacity-30 hover:bg-terminal-green hover:bg-opacity-5 transition-all duration-200 cursor-pointer group"
                >
                  <td className="py-3 px-3 text-terminal-cyan group-hover:text-terminal-cyan-bright">
                    {formatTime(trade.created_at)}
                  </td>
                  <td className="py-3 px-3 terminal-glow">
                    {trade.market_ticker.substring(0, 12)}
                  </td>
                  <td className="py-3 px-3 text-terminal-amber">
                    {trade.strategy.substring(0, 8).toUpperCase()}
                  </td>
                  <td className="py-3 px-3 text-terminal-green">
                    {trade.side === 'yes' ? 'YES' : 'NO '}
                  </td>
                  <td className="py-3 px-3 text-right tabular-nums text-terminal-green">
                    {trade.contracts}
                  </td>
                  <td className="py-3 px-3 text-right tabular-nums text-terminal-green">
                    {formatCents(trade.entry_price_cents)}
                  </td>
                  <td className="py-3 px-3 text-right tabular-nums text-terminal-green">
                    {formatCents(trade.exit_price_cents)}
                  </td>
                  <td className={`py-3 px-3 text-right tabular-nums font-bold ${getPnlClass(trade.pnl_cents)}`}>
                    {formatCents(trade.pnl_cents)}
                  </td>
                  <td className="py-3 px-3 text-terminal-cyan">
                    {getStatusSymbol(trade.status)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      {trades.length > 0 && (
        <div className="mt-4 pt-3 border-t border-terminal-green text-sm text-terminal-dim text-right tracking-wider">
          SHOWING {Math.min(trades.length, 10)} OF {trades.length} TRADES
        </div>
      )}
    </div>
  );
}
