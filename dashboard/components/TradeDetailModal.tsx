'use client';

import Modal from './Modal';
import { Trade } from '@/lib/types';

interface TradeDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  trade: Trade | null;
}

export default function TradeDetailModal({ isOpen, onClose, trade }: TradeDetailModalProps): JSX.Element | null {
  if (!trade) return null;

  const pnl = trade.pnl_cents ?? 0;
  const isProfitable = pnl > 0;
  const isLoss = pnl < 0;

  const formatCents = (cents: number) => `$${(cents / 100).toFixed(2)}`;
  const formatTime = (dateStr: string) => new Date(dateStr).toLocaleString();

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`TRADE #${trade.id}`}
      subtitle={trade.strategy?.toUpperCase() || 'MANUAL'}
      size="lg"
    >
      {/* P&L Banner */}
      <div className={`text-center py-4 mb-4 border ${
        isProfitable ? 'border-terminal-green bg-terminal-green bg-opacity-10' :
        isLoss ? 'border-terminal-red bg-terminal-red bg-opacity-10' :
        'border-terminal-dim'
      }`}>
        <div className="text-xs text-terminal-dim mb-1">REALIZED P&L</div>
        <div className={`text-4xl font-bold tabular-nums ${
          isProfitable ? 'text-terminal-green-bright terminal-glow' :
          isLoss ? 'text-terminal-red-bright' :
          'text-terminal-dim'
        }`}>
          {pnl >= 0 ? '+' : ''}{formatCents(pnl)}
        </div>
        {trade.entry_price_cents && trade.exit_price_cents && (
          <div className="text-sm text-terminal-dim mt-1">
            {trade.entry_price_cents}c → {trade.exit_price_cents}c
          </div>
        )}
      </div>

      {/* Trade Details Grid */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <DetailRow label="MARKET" value={trade.market_ticker} highlight />
        <DetailRow label="STRATEGY" value={trade.strategy || 'N/A'} />
        <DetailRow label="SIDE" value={trade.side} color={trade.side === 'YES' ? 'green' : 'red'} />
        <DetailRow label="ACTION" value={trade.action} />
        <DetailRow label="CONTRACTS" value={trade.contracts.toString()} />
        <DetailRow label="ENTRY PRICE" value={trade.entry_price_cents ? `${trade.entry_price_cents}c` : 'N/A'} />
        <DetailRow label="EXIT PRICE" value={trade.exit_price_cents ? `${trade.exit_price_cents}c` : 'Pending'} />
        <DetailRow label="STATUS" value={trade.status} color={trade.status === 'filled' ? 'green' : 'amber'} />
      </div>

      {/* Timestamps */}
      <div className="border-t border-terminal-green pt-4 mb-4">
        <div className="text-xs text-terminal-dim mb-2">TIMELINE</div>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-terminal-cyan">OPENED:</span>
            <span className="text-terminal-green tabular-nums">{formatTime(trade.created_at)}</span>
          </div>
          {trade.updated_at && trade.status === 'closed' && (
            <div className="flex justify-between">
              <span className="text-terminal-cyan">CLOSED:</span>
              <span className="text-terminal-green tabular-nums">{formatTime(trade.updated_at)}</span>
            </div>
          )}
          {trade.created_at && trade.updated_at && trade.status === 'closed' && (
            <div className="flex justify-between">
              <span className="text-terminal-cyan">DURATION:</span>
              <span className="text-terminal-amber tabular-nums">
                {formatDuration(new Date(trade.created_at), new Date(trade.updated_at))}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Reasoning */}
      {trade.reasoning && (
        <div className="border-t border-terminal-green pt-4">
          <div className="text-xs text-terminal-dim mb-2">TRADE REASONING</div>
          <div className="text-sm text-terminal-green bg-terminal-green bg-opacity-5 p-3 border border-terminal-green border-opacity-30">
            {trade.reasoning}
          </div>
        </div>
      )}

      {/* Order IDs */}
      <div className="border-t border-terminal-green pt-4 mt-4">
        <div className="text-xs text-terminal-dim mb-2">ORDER REFERENCES</div>
        <div className="text-xs font-mono text-terminal-dim">
          <div>Entry: {trade.order_id || 'N/A'}</div>
          {trade.exit_order_id && <div>Exit: {trade.exit_order_id}</div>}
        </div>
      </div>
    </Modal>
  );
}

interface DetailRowProps {
  label: string;
  value: string;
  highlight?: boolean;
  color?: 'green' | 'red' | 'amber' | 'cyan';
}

function DetailRow({ label, value, highlight, color }: DetailRowProps): JSX.Element {
  const getColorClass = () => {
    switch (color) {
      case 'green': return 'text-terminal-green';
      case 'red': return 'text-terminal-red';
      case 'amber': return 'text-terminal-amber';
      case 'cyan': return 'text-terminal-cyan';
      default: return highlight ? 'text-terminal-cyan' : 'text-terminal-green';
    }
  };

  return (
    <div>
      <div className="text-xs text-terminal-dim mb-1">{label}</div>
      <div className={`font-bold ${getColorClass()}`}>{value}</div>
    </div>
  );
}

function formatDuration(start: Date, end: Date): string {
  const diffMs = end.getTime() - start.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const remainingMins = diffMins % 60;

  if (diffHours > 0) {
    return `${diffHours}h ${remainingMins}m`;
  }
  return `${diffMins}m`;
}
