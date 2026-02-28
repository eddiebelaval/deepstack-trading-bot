import { ChartInterval } from './period';

function centsToDollars(cents: number): string {
  return (cents / 100).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatDollars(cents: number): string {
  return `$${centsToDollars(cents)}`;
}

export function formatCents(cents: number): string {
  return `$${centsToDollars(cents)}`;
}

export function formatPnL(cents: number): string {
  if (cents >= 0) {
    return `+$${centsToDollars(cents)}`;
  }
  return `-$${centsToDollars(Math.abs(cents))}`;
}

export function formatPercent(ratio: number, decimals: number = 1): string {
  return `${(ratio * 100).toFixed(decimals)}%`;
}

export function formatChartLabel(
  timestamp: string,
  interval: ChartInterval
): string {
  const d = new Date(timestamp);

  switch (interval) {
    case 'hourly':
      return d.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
      });
    case 'daily':
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      });
    case 'weekly':
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      });
    case 'monthly':
      return d.toLocaleDateString('en-US', {
        month: 'short',
        year: 'numeric',
      });
  }
}

export function formatVolume(volume: number): string {
  if (volume >= 1_000_000) {
    return `${(volume / 1_000_000).toFixed(1)}M`;
  }
  if (volume >= 1_000) {
    return `${(volume / 1_000).toFixed(1)}K`;
  }
  return String(volume);
}
