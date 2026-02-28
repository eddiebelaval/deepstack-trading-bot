export type TrendDirection = 'up' | 'down' | 'flat';

export interface Trend {
  value: number;
  percent: number;
  percentFormatted: string;
  direction: TrendDirection;
  color: string;
  favorable: boolean;
}

const EPSILON = 0.001;

const COLORS = {
  favorable: '#22c55e',
  unfavorable: '#ef4444',
  flat: 'rgba(255,255,255,0.4)',
} as const;

export function createTrend(
  current: number,
  previous: number,
  favorableDirection: TrendDirection = 'up'
): Trend {
  const absoluteChange = current - previous;
  const percent = previous === 0 ? 0 : (absoluteChange / previous) * 100;

  let direction: TrendDirection;
  if (Math.abs(percent) < EPSILON) {
    direction = 'flat';
  } else if (absoluteChange > 0) {
    direction = 'up';
  } else {
    direction = 'down';
  }

  const sign = direction === 'up' ? '+' : direction === 'down' ? '' : '';
  const percentFormatted =
    direction === 'flat'
      ? '0.0%'
      : `${sign}${percent.toFixed(1)}%`;

  const favorable =
    direction === 'flat' || direction === favorableDirection;

  let color: string;
  if (direction === 'flat') {
    color = COLORS.flat;
  } else if (favorable) {
    color = COLORS.favorable;
  } else {
    color = COLORS.unfavorable;
  }

  return {
    value: absoluteChange,
    percent,
    percentFormatted,
    direction,
    color,
    favorable,
  };
}
