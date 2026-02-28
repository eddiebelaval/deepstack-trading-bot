'use client';

import { useEffect, useState } from 'react';
import { getHoldings } from '@/lib/db-postgres';
import { createTrend, formatDollars, formatPnL } from '@/lib/analytics';
import type { Holding } from '@/lib/types';

export default function HoldingsTable() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const data = await getHoldings();
        setHoldings(data);
      } catch (e) {
        console.error('Failed to load holdings:', e);
      } finally {
        setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="panel p-6">
        <div className="text-xs text-terminal-dim mb-4 tracking-wider">HOLDINGS</div>
        <div className="text-terminal-dim/40 text-sm">Loading...</div>
      </div>
    );
  }

  if (holdings.length === 0) {
    return (
      <div className="panel p-6">
        <div className="text-xs text-terminal-dim mb-4 tracking-wider">HOLDINGS</div>
        <div className="text-terminal-dim/40 text-sm">No holdings</div>
      </div>
    );
  }

  return (
    <div className="panel p-6">
      <div className="text-xs text-terminal-dim mb-4 tracking-wider">HOLDINGS</div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-terminal-dim border-b border-white/5">
              <th className="text-left py-2 pr-4">TICKER</th>
              <th className="text-right py-2 pr-4">QTY</th>
              <th className="text-right py-2 pr-4">AVG COST</th>
              <th className="text-right py-2 pr-4">PRICE</th>
              <th className="text-right py-2 pr-4">VALUE</th>
              <th className="text-right py-2 pr-4">UNREAL P&L</th>
              <th className="text-right py-2 pr-4">DAY CHG</th>
              <th className="text-right py-2">PLATFORM</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => {
              const valueCents = h.qty * (h.current_price_cents || h.avg_cost_cents);
              const pnlTrend = createTrend(
                h.current_price_cents || h.avg_cost_cents,
                h.avg_cost_cents
              );

              return (
                <tr key={`${h.ticker}-${h.platform}`} className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="py-2 pr-4 text-white font-bold">{h.ticker}</td>
                  <td className="py-2 pr-4 text-right tabular-nums text-white/80">{h.qty}</td>
                  <td className="py-2 pr-4 text-right tabular-nums text-terminal-dim">
                    {formatDollars(h.avg_cost_cents)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums text-white/80">
                    {h.current_price_cents ? formatDollars(h.current_price_cents) : '--'}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums text-white/80">
                    {formatDollars(valueCents)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums" style={{ color: pnlTrend.color }}>
                    {formatPnL(h.unrealized_pnl_cents)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums" style={{ color: createTrend(h.day_change_cents, 0).color }}>
                    {formatPnL(h.day_change_cents)}
                  </td>
                  <td className="py-2 text-right text-terminal-dim uppercase">
                    {h.platform}
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
