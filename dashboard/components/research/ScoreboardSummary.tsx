'use client';

import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { TvIndicator } from '@/lib/research-types';
import { formatNum, valueColor, mean, CHART_COLORS, CHART_TOOLTIP_STYLE } from '@/lib/research-utils';

interface ScoreboardSummaryProps {
  indicators: TvIndicator[];
}

/** Build histogram buckets from composite scores */
function buildHistogram(indicators: TvIndicator[], buckets: number = 10) {
  const scores = indicators.map(i => i.composite_score ?? 0);
  if (scores.length === 0) return [];

  const min = Math.floor(Math.min(...scores));
  const max = Math.ceil(Math.max(...scores));
  const range = max - min || 1;
  const step = range / buckets;

  const bins: { range: string; count: number }[] = [];
  for (let i = 0; i < buckets; i++) {
    const lo = min + i * step;
    const hi = lo + step;
    const count = scores.filter(s => s >= lo && (i === buckets - 1 ? s <= hi : s < hi)).length;
    bins.push({ range: `${lo.toFixed(1)}`, count });
  }
  return bins;
}

export default function ScoreboardSummary({ indicators }: ScoreboardSummaryProps) {
  const stats = useMemo(() => {
    if (indicators.length === 0) return null;

    const scores = indicators.map(i => i.composite_score ?? 0);
    const sharpes = indicators.map(i => i.avg_sharpe ?? 0);
    const avgScore = mean(scores);
    const avgSharpe = mean(sharpes);

    const topIdx = scores.indexOf(Math.max(...scores));
    const top = indicators[topIdx];

    return { count: indicators.length, avgScore, avgSharpe, top };
  }, [indicators]);

  const histogram = useMemo(() => buildHistogram(indicators), [indicators]);

  if (!stats) return null;

  const cards = [
    { label: 'INDICATORS', value: String(stats.count), color: 'text-terminal-cyan' },
    { label: 'AVG SCORE', value: formatNum(stats.avgScore), color: valueColor(stats.avgScore) },
    { label: 'AVG SHARPE', value: formatNum(stats.avgSharpe), color: valueColor(stats.avgSharpe) },
    { label: 'TOP PERFORMER', value: stats.top?.script_name ?? '--', sub: formatNum(stats.top?.composite_score ?? null), color: 'text-terminal-green' },
  ];

  return (
    <div className="space-y-4 mb-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {cards.map((card, i) => (
          <div
            key={card.label}
            className="panel p-3 animate-fade-in"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-1">
              {card.label}
            </div>
            <div className={`text-2xl font-bold tabular-nums truncate ${card.color}`}>
              {card.value}
            </div>
            {card.sub && (
              <div className="text-[10px] text-terminal-dim tabular-nums mt-0.5">
                Score: {card.sub}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Score distribution histogram */}
      {histogram.length > 0 && (
        <div className="panel p-4">
          <div className="text-[9px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
            SCORE DISTRIBUTION
          </div>
          <div className="h-[140px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={histogram} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                <XAxis
                  dataKey="range"
                  tick={{ fill: CHART_COLORS.greenDim, fontSize: 10 }}
                  axisLine={{ stroke: CHART_COLORS.axisLine }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: CHART_COLORS.greenDim, fontSize: 9 }}
                  axisLine={{ stroke: CHART_COLORS.axisLine }}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={CHART_TOOLTIP_STYLE}
                  formatter={(value: number | undefined) => [value ?? 0, 'Count']}
                  labelFormatter={(label) => `Score: ${label}`}
                />
                <Bar
                  dataKey="count"
                  fill={CHART_COLORS.green}
                  fillOpacity={0.6}
                  radius={[2, 2, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
