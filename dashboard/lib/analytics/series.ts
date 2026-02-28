import { Trend, createTrend } from './trend';

export interface SeriesPoint {
  date: string;
  value: number;
  trend: Trend | null;
}

export interface Series {
  points: SeriesPoint[];
  trend: Trend;
  length: number;
}

export function createSeries(
  values: { date: string; value: number }[]
): Series {
  if (values.length === 0) {
    return {
      points: [],
      trend: createTrend(0, 0),
      length: 0,
    };
  }

  const points: SeriesPoint[] = values.map((v, i) => ({
    date: v.date,
    value: v.value,
    trend: i === 0 ? null : createTrend(v.value, values[i - 1].value),
  }));

  const first = values[0].value;
  const last = values[values.length - 1].value;

  return {
    points,
    trend: createTrend(last, first),
    length: values.length,
  };
}
