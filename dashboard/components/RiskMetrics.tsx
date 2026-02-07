'use client';

import { RiskMetrics } from '@/lib/types';

interface RiskMetricsProps {
  metrics: RiskMetrics;
}

export default function RiskMetricsCard({ metrics }: RiskMetricsProps) {
  // Safe defaults for null/undefined values
  const safeMetrics = {
    daily_loss_limit_cents: metrics?.daily_loss_limit_cents ?? 10000,
    daily_loss_used_cents: metrics?.daily_loss_used_cents ?? 0,
    risk_percentage: metrics?.risk_percentage ?? 0,
    kelly_fraction: metrics?.kelly_fraction ?? 0.5,
    max_position_size_cents: metrics?.max_position_size_cents ?? 5000,
    positions_at_risk: metrics?.positions_at_risk ?? 0,
  };

  const formatCents = (cents: number) => {
    return `$${((cents ?? 0) / 100).toFixed(2)}`;
  };

  const getRiskClass = (percentage: number) => {
    if (percentage >= 80) return 'status-error';
    if (percentage >= 50) return 'text-terminal-amber amber-glow';
    if (percentage >= 30) return 'text-terminal-amber-dim';
    return 'text-terminal-green terminal-glow';
  };

  const riskBarWidth = Math.min(safeMetrics.risk_percentage, 100);

  return (
    <div className="border border-terminal-green p-4">
      {/* Header */}
      <div className="border-b border-terminal-green pb-2 mb-4">
        <div className="text-xs text-terminal-dim mb-1">RISK MANAGEMENT</div>
        <div className="text-lg font-bold terminal-glow tracking-wide">
          LIMITS & EXPOSURE
        </div>
      </div>

      {/* Metrics */}
      <div className="space-y-5">
        {/* Daily Loss Limit */}
        <div>
          <div className="flex justify-between text-sm mb-3 tracking-wider">
            <span className="text-terminal-dim">DAILY LOSS LIMIT</span>
            <span className={`font-bold ${getRiskClass(safeMetrics.risk_percentage)}`}>
              {safeMetrics.risk_percentage.toFixed(0)}% USED
            </span>
          </div>
          <div className="flex justify-between text-base tabular-nums mb-3">
            <span className="text-terminal-green">{formatCents(safeMetrics.daily_loss_used_cents)}</span>
            <span className="text-terminal-dim">
              / {formatCents(safeMetrics.daily_loss_limit_cents)}
            </span>
          </div>
          {/* Progress bar */}
          <div className="w-full h-3 border border-terminal-green relative">
            <div
              className={`h-full ${getRiskClass(safeMetrics.risk_percentage)} bg-current transition-all duration-500`}
              style={{ width: `${riskBarWidth}%` }}
            />
          </div>
        </div>

        {/* Kelly Fraction - CYAN for config info */}
        <div className="flex justify-between items-baseline pt-4 border-t border-terminal-green gap-4">
          <span className="text-sm text-terminal-cyan-dim tracking-wider">KELLY FRACTION:</span>
          <span className="text-xl font-bold tabular-nums text-terminal-cyan">
            {safeMetrics.kelly_fraction.toFixed(2)}
          </span>
        </div>

        {/* Max Position Size - CYAN for config info */}
        <div className="flex justify-between items-baseline gap-4">
          <span className="text-sm text-terminal-cyan-dim tracking-wider">MAX POSITION:</span>
          <span className="text-xl font-bold tabular-nums text-terminal-cyan">
            {formatCents(safeMetrics.max_position_size_cents)}
          </span>
        </div>

        {/* Positions at Risk - AMBER for attention */}
        <div className="flex justify-between items-baseline gap-4">
          <span className="text-sm text-terminal-amber-dim tracking-wider">AT RISK:</span>
          <span className={`text-xl font-bold tabular-nums ${
            safeMetrics.positions_at_risk > 0 ? 'text-terminal-amber amber-glow' : 'text-terminal-green'
          }`}>
            {safeMetrics.positions_at_risk.toString().padStart(2, '0')}
          </span>
        </div>
      </div>
    </div>
  );
}
