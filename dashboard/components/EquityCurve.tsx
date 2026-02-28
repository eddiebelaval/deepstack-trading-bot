'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { getBalanceSnapshots } from '@/lib/db-postgres';
import { resolvePeriod, formatDollars, formatChartLabel } from '@/lib/analytics';
import type { PeriodName } from '@/lib/analytics';
import type { BalanceSnapshot } from '@/lib/types';

type PlatformFilter = 'all' | 'kalshi' | 'ibkr';

export default function EquityCurve() {
  const [snapshots, setSnapshots] = useState<BalanceSnapshot[]>([]);
  const [period, setPeriod] = useState<PeriodName>('90D');
  const [platform, setPlatform] = useState<PlatformFilter>('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const data = await getBalanceSnapshots(platform === 'all' ? undefined : platform);
        setSnapshots(data);
      } catch (e) {
        console.error('Failed to load balance snapshots:', e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [platform]);

  const { chartData, isProfit } = useMemo(() => {
    if (!snapshots.length) return { chartData: [], isProfit: true };

    const resolved = resolvePeriod(period);
    const chrono = [...snapshots].reverse();
    const filtered = chrono.filter(
      (s) => new Date(s.date) >= resolved.startDate
    );

    if (filtered.length < 2) return { chartData: [], isProfit: true };

    const first = filtered[0].end_balance_cents;
    const last = filtered[filtered.length - 1].end_balance_cents;

    return {
      chartData: filtered.map((s) => ({
        date: s.date,
        value: s.end_balance_cents / 100,
        label: formatChartLabel(s.date, resolved.interval),
      })),
      isProfit: last >= first,
    };
  }, [snapshots, period]);

  const periods: PeriodName[] = ['7D', '30D', '90D', 'YTD', 'ALL'];
  const platforms: PlatformFilter[] = ['all', 'kalshi', 'ibkr'];

  const colors = isProfit
    ? { line: '#22c55e', glow: 'rgba(34, 197, 94, 0.5)' }
    : { line: '#ef4444', glow: 'rgba(239, 68, 68, 0.5)' };

  return (
    <div className="panel p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs text-terminal-dim tracking-wider">EQUITY CURVE</div>
        <div className="flex gap-3">
          {/* Platform filter */}
          <div className="flex gap-1 bg-terminal-bg rounded-lg p-1">
            {platforms.map((p) => (
              <button
                key={p}
                onClick={() => setPlatform(p)}
                className={`px-2 py-1 text-xs font-bold rounded-md transition-all uppercase ${
                  platform === p
                    ? 'bg-white/10 text-white/60 border border-white/20'
                    : 'text-terminal-dim hover:text-white hover:bg-white/5'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
          {/* Period selector */}
          <div className="flex gap-1 bg-terminal-bg rounded-lg p-1">
            {periods.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${
                  period === p
                    ? isProfit
                      ? 'bg-green-500/20 text-green-400 border border-green-500/40'
                      : 'bg-red-500/20 text-red-400 border border-red-500/40'
                    : 'text-terminal-dim hover:text-white hover:bg-white/5'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="h-56 flex items-center justify-center">
          <div className="text-terminal-dim/40 text-sm">Loading...</div>
        </div>
      ) : chartData.length < 2 ? (
        <div className="h-56 flex items-center justify-center">
          <div className="text-center">
            <div className="text-terminal-dim/40 text-sm mb-2">NO DATA</div>
            <div className="text-terminal-dim/30 text-xs">
              Balance snapshots will appear once the bot starts syncing
            </div>
          </div>
        </div>
      ) : (
        <div className="h-56 -mx-2">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={colors.line} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={colors.line} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="rgba(255,255,255,0.05)"
                vertical={false}
              />
              <XAxis
                dataKey="label"
                tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }}
                axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => `$${v}`}
                domain={['dataMin - 5', 'dataMax + 5']}
                width={55}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'rgba(30,30,40,0.95)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: '8px',
                  fontSize: '12px',
                  fontFamily: 'monospace',
                }}
                formatter={(value: number | undefined) => [formatDollars(Math.round((value ?? 0) * 100)), 'Balance']}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={colors.line}
                strokeWidth={2}
                fill="url(#equityGradient)"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
