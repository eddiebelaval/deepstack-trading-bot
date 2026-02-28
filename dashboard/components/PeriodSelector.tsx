'use client';

import type { PeriodName } from '@/lib/analytics';

interface PeriodSelectorProps {
  value: PeriodName;
  onChange: (period: PeriodName) => void;
  periods?: PeriodName[];
  isProfit?: boolean;
}

const DEFAULT_PERIODS: PeriodName[] = ['1D', '7D', 'MTD', '30D', '90D', 'YTD', 'ALL'];

export default function PeriodSelector({
  value,
  onChange,
  periods = DEFAULT_PERIODS,
  isProfit = true,
}: PeriodSelectorProps) {
  return (
    <div className="flex gap-1 bg-terminal-bg rounded-lg p-1">
      {periods.map((period) => (
        <button
          key={period}
          onClick={() => onChange(period)}
          className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${
            value === period
              ? isProfit
                ? 'bg-green-500/20 text-green-400 border border-green-500/40'
                : 'bg-red-500/20 text-red-400 border border-red-500/40'
              : 'text-terminal-dim hover:text-white hover:bg-white/5'
          }`}
        >
          {period}
        </button>
      ))}
    </div>
  );
}
