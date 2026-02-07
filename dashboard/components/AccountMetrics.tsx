'use client';

import { useMemo } from 'react';
import { AccountMetrics } from '@/lib/types';
import Sparkline from './Sparkline';

interface AccountMetricsProps {
  metrics: AccountMetrics;
  balanceHistory?: number[];
  pnlHistory?: number[];
}

function formatCents(cents: number): string {
  return `$${((cents ?? 0) / 100).toFixed(2)}`;
}

function formatPercentage(pct: number): string {
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

function generateTrendData(targetValue: number, variance: number, trendFactor: number): number[] {
  return Array.from({ length: 10 }, (_, i) => {
    const randomVariance = (Math.random() - 0.5) * variance;
    const trend = (i / 9) * trendFactor;
    return targetValue + trend + randomVariance;
  });
}

function getPnlColorClass(pnlCents: number, isBright: boolean): string {
  if (pnlCents > 0) {
    return isBright ? 'text-terminal-amber-bright amber-glow' : 'text-terminal-amber';
  }
  if (pnlCents < 0) {
    return isBright ? 'status-error' : 'text-terminal-red-dim';
  }
  return isBright ? 'text-terminal-amber' : 'text-terminal-amber-dim';
}

export default function AccountMetricsCard({ metrics, balanceHistory, pnlHistory }: AccountMetricsProps): JSX.Element {
  const safeMetrics = {
    balance_cents: metrics?.balance_cents ?? 0,
    daily_pnl_cents: metrics?.daily_pnl_cents ?? 0,
    daily_pnl_percentage: metrics?.daily_pnl_percentage ?? 0,
    total_positions: metrics?.total_positions ?? 0,
    available_balance_cents: metrics?.available_balance_cents ?? 0,
  };

  const balanceTrend = useMemo(() => {
    if (balanceHistory && balanceHistory.length > 1) return balanceHistory;
    const base = safeMetrics.balance_cents;
    return generateTrendData(base * 0.95, base * 0.02, base * 0.03);
  }, [balanceHistory, safeMetrics.balance_cents]);

  const pnlTrend = useMemo(() => {
    if (pnlHistory && pnlHistory.length > 1) return pnlHistory;
    const current = safeMetrics.daily_pnl_cents;
    return generateTrendData(0, Math.abs(current * 0.3), current);
  }, [pnlHistory, safeMetrics.daily_pnl_cents]);

  const pnlColor = safeMetrics.daily_pnl_cents >= 0 ? '#FFBF00' : '#FF4444';

  return (
    <div className="border border-terminal-green p-4">
      {/* Header */}
      <div className="border-b border-terminal-green pb-2 mb-4">
        <div className="text-xs text-terminal-dim mb-1">ACCOUNT</div>
        <div className="text-lg font-bold terminal-glow tracking-wide">
          BALANCE & P/L
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="space-y-5">
        {/* Balance */}
        <div className="flex justify-between items-center gap-4">
          <span className="text-sm text-terminal-dim tracking-wider">BALANCE:</span>
          <div className="flex items-center gap-3">
            <Sparkline
              data={balanceTrend}
              width={50}
              height={18}
              color="#00FF41"
              showDot={true}
            />
            <span className="text-3xl font-bold tabular-nums terminal-glow-bright">
              {formatCents(safeMetrics.balance_cents)}
            </span>
          </div>
        </div>

        {/* Daily P/L */}
        <div className="flex justify-between items-center gap-4">
          <span className="text-sm text-terminal-amber-dim tracking-wider">DAILY P/L:</span>
          <div className="flex items-center gap-3">
            <Sparkline
              data={pnlTrend}
              width={50}
              height={18}
              color={pnlColor}
              showDot={true}
            />
            <div className="text-right">
              <div className={`text-2xl font-bold tabular-nums ${getPnlColorClass(safeMetrics.daily_pnl_cents, true)}`}>
                {safeMetrics.daily_pnl_cents >= 0 ? '+' : ''}{formatCents(safeMetrics.daily_pnl_cents)}
              </div>
              <div className={`text-sm tabular-nums mt-1 ${getPnlColorClass(safeMetrics.daily_pnl_cents, false)}`}>
                {formatPercentage(safeMetrics.daily_pnl_percentage)}
              </div>
            </div>
          </div>
        </div>

        {/* Secondary Metrics */}
        <div className="border-t border-terminal-green pt-5">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-sm text-terminal-cyan-dim tracking-wider mb-2">POSITIONS</div>
              <div className="text-xl font-bold tabular-nums text-terminal-cyan">
                {safeMetrics.total_positions.toString().padStart(2, '0')}
              </div>
            </div>
            <div>
              <div className="text-sm text-terminal-cyan-dim tracking-wider mb-2">AVAILABLE</div>
              <div className="text-xl font-bold tabular-nums text-terminal-cyan">
                {formatCents(safeMetrics.available_balance_cents)}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
