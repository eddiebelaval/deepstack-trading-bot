'use client';

import { useState } from 'react';
import { Position } from '@/lib/types';
import CandlestickChart from './CandlestickChart';

interface PositionsTableProps {
  positions: Position[];
}

function extractSeries(ticker: string): string {
  // KXBTC-26FEB0912-B79125 → KXBTC
  const dash = ticker.indexOf('-');
  return dash > 0 ? ticker.substring(0, dash) : ticker;
}

export default function PositionsTable({ positions }: PositionsTableProps) {
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null);

  const formatCents = (cents: number | null) => {
    if (cents === null || cents === undefined) return '---';
    return `$${(cents / 100).toFixed(2)}`;
  };

  const formatPrice = (cents: number | null) => {
    if (cents === null || cents === undefined) return '---';
    return `${cents}c`;
  };

  const formatVolume = (vol: number | null) => {
    if (vol === null || vol === undefined || vol === 0) return '---';
    if (vol >= 1000000) return `${(vol / 1000000).toFixed(1)}M`;
    if (vol >= 1000) return `${(vol / 1000).toFixed(1)}K`;
    return vol.toString();
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

  const getPriceChangeDisplay = (pos: Position) => {
    const change = pos.price_change_cents;
    if (change === null || change === undefined) return { text: '---', cls: 'text-terminal-dim' };
    const sign = change >= 0 ? '+' : '';
    const cls = change > 0 ? 'text-green-400' : change < 0 ? 'text-red-400' : 'text-terminal-dim';
    return { text: `${sign}${change}c`, cls };
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
          const priceChange = getPriceChangeDisplay(pos);
          const isExpanded = expandedTicker === pos.ticker;
          return (
            <div key={pos.ticker} className="border border-terminal-green/30 rounded overflow-hidden">
              <button
                onClick={() => setExpandedTicker(isExpanded ? null : pos.ticker)}
                className="w-full p-3 space-y-1 text-left"
              >
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
                  <span className={priceChange.cls}>24H: {priceChange.text}</span>
                  <span>VOL: {formatVolume(pos.volume_24h)}</span>
                </div>
              </button>
              {isExpanded && (
                <div className="px-3 pb-3 border-t border-terminal-green/20">
                  <CandlestickChart ticker={pos.ticker} series={extractSeries(pos.ticker)} />
                </div>
              )}
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
              <th className="text-right py-2 px-2">24H CHG</th>
              <th className="text-right py-2 px-2">AVG ENTRY</th>
              <th className="text-right py-2 px-2">VALUE</th>
              <th className="text-right py-2 px-2">UNREAL P&L</th>
              <th className="text-right py-2 px-2">VOL 24H</th>
              <th className="text-right py-2 px-2">OI</th>
              <th className="text-right py-2 pl-2">FEES</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const unrealizedPnl = computeUnrealizedPnl(pos);
              const priceChange = getPriceChangeDisplay(pos);
              const isExpanded = expandedTicker === pos.ticker;
              return (
                <tr key={pos.ticker} className="group">
                  <td colSpan={11} className="p-0">
                    <div
                      className="grid grid-cols-[1fr_auto_auto_auto_auto_auto_auto_auto_auto_auto_auto] items-center border-b border-terminal-green/10 hover:bg-terminal-green/5 transition-colors cursor-pointer"
                      onClick={() => setExpandedTicker(isExpanded ? null : pos.ticker)}
                    >
                      <div className="py-2 pr-3 text-terminal-green max-w-[200px] truncate" title={pos.market_title || pos.ticker}>
                        <span className="mr-1 text-terminal-dim text-[10px]">{isExpanded ? '[-]' : '[+]'}</span>
                        {pos.market_title || pos.ticker}
                      </div>
                      <div className={`py-2 px-2 text-center font-bold ${pos.side === 'yes' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                        {pos.side.toUpperCase()}
                      </div>
                      <div className="py-2 px-2 text-right">{pos.contracts}</div>
                      <div className="py-2 px-2 text-right">{formatPrice(pos.current_price)}</div>
                      <div className={`py-2 px-2 text-right ${priceChange.cls}`}>{priceChange.text}</div>
                      <div className="py-2 px-2 text-right">{pos.avg_entry_price_cents ? formatPrice(pos.avg_entry_price_cents) : '---'}</div>
                      <div className="py-2 px-2 text-right">{formatCents(pos.market_value_cents)}</div>
                      <div className={`py-2 px-2 text-right ${getPnlClass(unrealizedPnl)}`}>
                        {unrealizedPnl !== null ? `${unrealizedPnl >= 0 ? '+' : ''}${formatCents(unrealizedPnl)}` : '---'}
                      </div>
                      <div className="py-2 px-2 text-right text-terminal-dim">{formatVolume(pos.volume_24h)}</div>
                      <div className="py-2 px-2 text-right text-terminal-dim">{formatVolume(pos.open_interest)}</div>
                      <div className="py-2 pl-2 text-right text-terminal-dim">{formatCents(pos.fees_paid)}</div>
                    </div>
                    {isExpanded && (
                      <div className="px-4 py-3 bg-black/30 border-b border-terminal-green/10">
                        <CandlestickChart ticker={pos.ticker} series={extractSeries(pos.ticker)} />
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
