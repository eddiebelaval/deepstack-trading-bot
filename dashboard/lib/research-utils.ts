// Shared utilities for TV Script Research pages

/** Format a nullable number with fixed decimals */
export function formatNum(val: number | null, decimals: number = 2): string {
  if (val === null || val === undefined) return '--';
  return val.toFixed(decimals);
}

/** Format a nullable number as a percentage string */
export function formatPct(val: number | null): string {
  if (val === null || val === undefined) return '--';
  return `${val.toFixed(1)}%`;
}

/** Return a Tailwind text-color class based on sign */
export function valueColor(val: number | null): string {
  if (val === null || val === undefined) return 'text-terminal-dim';
  if (val > 0) return 'text-terminal-green';
  if (val < 0) return 'text-terminal-red';
  return 'text-terminal-amber';
}

/** Arithmetic mean of an array of numbers */
export function mean(arr: number[]): number {
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

/** Build a TradingView link — direct URL if available, search fallback otherwise */
export function tvLink(scriptUrl: string | null | undefined, scriptName: string): string {
  if (scriptUrl) return scriptUrl;
  return `https://www.tradingview.com/scripts/?q=${encodeURIComponent(scriptName)}`;
}

/** Consistent chart color tokens derived from the terminal theme */
export const CHART_COLORS = {
  green: '#00FF41',
  greenDim: '#00AA2B',
  amber: '#FFBF00',
  cyan: '#00FFFF',
  red: '#FF0000',
  bg: '#16161f',
  gridLine: 'rgba(0,255,65,0.1)',
  axisLine: 'rgba(0,255,65,0.2)',
} as const;

/** Shared Recharts tooltip style */
export const CHART_TOOLTIP_STYLE = {
  background: CHART_COLORS.bg,
  border: `1px solid rgba(0,255,65,0.3)`,
  borderRadius: '4px',
  fontSize: '11px',
  color: CHART_COLORS.green,
} as const;
