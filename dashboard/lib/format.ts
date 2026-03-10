import type { StrategyStatus } from './types';

// ---------------------------------------------------------------------------
// Currency
// ---------------------------------------------------------------------------

export function centsToUSD(cents: number): string {
  return (cents / 100).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
  });
}

// ---------------------------------------------------------------------------
// Time
// ---------------------------------------------------------------------------

export function shortTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function fullTime(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

export function stripMarkdown(text: string): string {
  return text
    .replace(/#{1,6}\s*/g, '')
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
    .replace(/---+/g, '')
    .replace(/\n+/g, ' ')
    .trim();
}

export function truncateNote(text: string, max = 80): string {
  const clean = stripMarkdown(text);
  if (clean.length <= max) return clean;
  return clean.slice(0, max) + '...';
}

// ---------------------------------------------------------------------------
// Strategy health display
// ---------------------------------------------------------------------------

type HealthKey = NonNullable<StrategyStatus['health_status']>;

const HEALTH_MAP: Record<HealthKey, { dot: string; label: string; color: string }> = {
  healthy:  { dot: 'bg-terminal-green',      label: 'HEALTHY',  color: 'text-terminal-green' },
  warning:  { dot: 'bg-terminal-amber',      label: 'WARNING',  color: 'text-terminal-amber' },
  critical: { dot: 'bg-terminal-red',        label: 'CRITICAL', color: 'text-terminal-red' },
  unknown:  { dot: 'bg-terminal-green-dim/40', label: 'UNKNOWN',  color: 'text-terminal-dim' },
};

const HEALTH_DEFAULT = HEALTH_MAP.unknown;

function resolveHealth(h: StrategyStatus['health_status']) {
  return (h && HEALTH_MAP[h]) || HEALTH_DEFAULT;
}

export function healthDot(h: StrategyStatus['health_status']): string {
  return resolveHealth(h).dot;
}

export function healthLabel(h: StrategyStatus['health_status']): string {
  return resolveHealth(h).label;
}

export function healthColor(h: StrategyStatus['health_status']): string {
  return resolveHealth(h).color;
}

// ---------------------------------------------------------------------------
// Regime colors (consolidated — used by AnalyticsPanel, StrategiesPanel, etc.)
// ---------------------------------------------------------------------------

export const REGIME_COLORS: Record<string, string> = {
  high_vol_choppy: '#FF0000',
  low_vol_calm: '#00FF41',
  trending_up: '#00D4FF',
  trending_down: '#FFBF00',
  mean_reverting: '#9B59B6',
};

export function regimeColor(regime: string): string {
  return REGIME_COLORS[regime] ?? '#00AA2B';
}

// ---------------------------------------------------------------------------
// Gate check value formatting (used by graduation page)
// ---------------------------------------------------------------------------

type GateFormat = 'number' | 'percent' | 'cents' | 'pct' | 'days';

export function formatGateValue(v: number, format: GateFormat): string {
  switch (format) {
    case 'percent':
      return `${(v * 100).toFixed(1)}%`;
    case 'cents':
      return `$${(v / 100).toFixed(2)}`;
    case 'pct':
      return `${v.toFixed(1)}%`;
    default:
      return v.toFixed(0);
  }
}

// ---------------------------------------------------------------------------
// Common display transforms
// ---------------------------------------------------------------------------

export function formatStrategyName(name: string): string {
  return (name ?? 'UNKNOWN').replace(/_/g, ' ').toUpperCase();
}
