export type PeriodName = '1D' | '7D' | 'MTD' | '30D' | '90D' | 'YTD' | 'ALL';
export type ChartInterval = 'hourly' | 'daily' | 'weekly' | 'monthly';

export interface Period {
  startDate: Date;
  endDate: Date;
  days: number;
  interval: ChartInterval;
  label: string;
  labelShort: string;
}

const LABELS: Record<PeriodName, { label: string; labelShort: string }> = {
  '1D': { label: 'Today', labelShort: '1D' },
  '7D': { label: 'Past 7 Days', labelShort: '7D' },
  'MTD': { label: 'Month to Date', labelShort: 'MTD' },
  '30D': { label: 'Past 30 Days', labelShort: '30D' },
  '90D': { label: 'Past 90 Days', labelShort: '90D' },
  'YTD': { label: 'Year to Date', labelShort: 'YTD' },
  'ALL': { label: 'All Time', labelShort: 'ALL' },
};

function resolveInterval(days: number): ChartInterval {
  if (days <= 1) return 'hourly';
  if (days <= 90) return 'daily';
  if (days <= 366) return 'weekly';
  return 'monthly';
}

function daysBetween(start: Date, end: Date): number {
  return Math.max(1, Math.round((end.getTime() - start.getTime()) / 86_400_000));
}

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

export function resolvePeriod(name: PeriodName): Period {
  const now = new Date();
  const endDate = now;
  let startDate: Date;

  switch (name) {
    case '1D':
      startDate = startOfDay(now);
      break;
    case '7D':
      startDate = new Date(now.getTime() - 7 * 86_400_000);
      break;
    case 'MTD':
      startDate = new Date(now.getFullYear(), now.getMonth(), 1);
      break;
    case '30D':
      startDate = new Date(now.getTime() - 30 * 86_400_000);
      break;
    case '90D':
      startDate = new Date(now.getTime() - 90 * 86_400_000);
      break;
    case 'YTD':
      startDate = new Date(now.getFullYear(), 0, 1);
      break;
    case 'ALL':
      startDate = new Date(0);
      break;
  }

  const days = daysBetween(startDate, endDate);
  const interval = resolveInterval(days);
  const { label, labelShort } = LABELS[name];

  return { startDate, endDate, days, interval, label, labelShort };
}

export function customPeriod(start: Date, end: Date): Period {
  const days = daysBetween(start, end);
  const interval = resolveInterval(days);

  return {
    startDate: start,
    endDate: end,
    days,
    interval,
    label: `${start.toLocaleDateString()} - ${end.toLocaleDateString()}`,
    labelShort: `${days}D`,
  };
}
