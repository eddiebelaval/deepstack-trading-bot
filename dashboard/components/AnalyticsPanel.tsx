'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts';
import { formatStrategyName, regimeColor } from '@/lib/format';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ChartView =
  | 'daily_pnl'
  | 'strategy_perf'
  | 'regime_timeline'
  | 'win_rate'
  | 'fitness_heatmap'
  | 'trade_scatter';

interface ViewConfig {
  key: ChartView;
  label: string;
  shortLabel: string;
}

const VIEWS: ViewConfig[] = [
  { key: 'daily_pnl', label: 'DAILY P&L', shortLabel: 'P&L' },
  { key: 'strategy_perf', label: 'STRATEGY PERF', shortLabel: 'STRAT' },
  { key: 'win_rate', label: 'WIN RATE TREND', shortLabel: 'WR' },
  { key: 'regime_timeline', label: 'REGIME TIMELINE', shortLabel: 'REGIME' },
  { key: 'trade_scatter', label: 'TRADE MAP', shortLabel: 'TRADES' },
  { key: 'fitness_heatmap', label: 'FITNESS MATRIX', shortLabel: 'FIT' },
];

const TIME_RANGES = [
  { days: 7, label: '7D' },
  { days: 14, label: '14D' },
  { days: 30, label: '30D' },
  { days: 90, label: '90D' },
  { days: 365, label: '1Y' },
];

// Terminal palette
const GREEN = '#00FF41';
const GREEN_DIM = '#00AA2B';
const RED = '#FF0000';
const CYAN = '#00D4FF';
const AMBER = '#FFBF00';
const BG = '#12121a';
const GRID = 'rgba(0, 255, 65, 0.08)';
const AXIS = 'rgba(0, 255, 65, 0.2)';

const STRATEGY_COLORS: Record<string, string> = {
  calibration_edge: GREEN,
  market_making: CYAN,
  momentum: AMBER,
  mean_reversion: '#FF6B6B',
  high_probability_bonds: '#9B59B6',
  stock_momentum: '#E67E22',
  crisis_alpha: RED,
  settlement_betting: '#1ABC9C',
};

function stratColor(name: string): string {
  return STRATEGY_COLORS[name] || GREEN_DIM;
}

// Tooltip shared style
const tooltipStyle = {
  background: BG,
  border: `1px solid rgba(0, 255, 65, 0.3)`,
  borderRadius: 4,
  fontSize: 10,
  color: GREEN,
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- recharts Formatter types are overly strict
type AnyFormatter = any;

/** Safe .toFixed() — guards against null/undefined values from recharts */
function safeFixed(v: unknown, digits: number): string {
  return typeof v === 'number' && !isNaN(v) ? v.toFixed(digits) : '—';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AnalyticsPanel() {
  const [view, setView] = useState<ChartView>('daily_pnl');
  const [days, setDays] = useState(30);
  const [rawData, setRawData] = useState<unknown[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/analytics?view=${view}&days=${days}`);
      if (res.ok) {
        const json = await res.json();
        setRawData(json.data || []);
      }
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [view, days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ---------------------------------------------------------------------------
  // Chart renderers
  // ---------------------------------------------------------------------------

  const chart = useMemo(() => {
    if (loading) {
      return (
        <div className="flex items-center justify-center h-full text-[10px] text-terminal-dim">
          LOADING<span className="animate-cursor-blink">_</span>
        </div>
      );
    }

    if (!rawData || rawData.length === 0) {
      return (
        <div className="flex items-center justify-center h-full text-[10px] text-terminal-dim">
          NO DATA — START BOT TO GENERATE
        </div>
      );
    }

    switch (view) {
      case 'daily_pnl':
        return <DailyPnLChart data={rawData as DailyPnLRow[]} />;
      case 'strategy_perf':
        return <StrategyPerfChart data={rawData as StrategyPerfRow[]} />;
      case 'win_rate':
        return <WinRateChart data={rawData as WinRateRow[]} />;
      case 'regime_timeline':
        return <RegimeChart data={rawData as RegimeRow[]} />;
      case 'trade_scatter':
        return <TradeScatterChart data={rawData as TradeScatterRow[]} />;
      case 'fitness_heatmap':
        return <FitnessHeatmap data={rawData as FitnessRow[]} />;
      default:
        return null;
    }
  }, [view, rawData, loading]);

  return (
    <div className="panel">
      {/* Header: view tabs + time range */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between px-3 py-2 border-b border-terminal-green/20 gap-2">
        {/* View tabs */}
        <div className="flex items-center gap-1 flex-wrap">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              onClick={() => setView(v.key)}
              className={`px-2 py-1 text-[9px] font-bold tracking-wider border rounded transition-all ${
                view === v.key
                  ? 'border-terminal-green bg-terminal-green/10 text-terminal-green'
                  : 'border-terminal-dim/20 text-terminal-dim hover:border-terminal-green/30 hover:text-terminal-green-dim'
              }`}
            >
              <span className="hidden sm:inline">{v.label}</span>
              <span className="sm:hidden">{v.shortLabel}</span>
            </button>
          ))}
        </div>

        {/* Time range (only shown for time-series views) */}
        {!new Set<ChartView>(['strategy_perf', 'fitness_heatmap', 'trade_scatter']).has(view) && (
          <div className="flex items-center gap-1">
            {TIME_RANGES.map((r) => (
              <button
                key={r.days}
                onClick={() => setDays(r.days)}
                className={`px-1.5 py-0.5 text-[9px] tracking-wider rounded transition-all ${
                  days === r.days
                    ? 'text-terminal-cyan bg-terminal-cyan/10 border border-terminal-cyan/30'
                    : 'text-terminal-dim hover:text-terminal-cyan/70'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Chart area */}
      <div className="h-[280px] p-3">{chart}</div>
    </div>
  );
}

// ===========================================================================
// Sub-charts
// ===========================================================================

// -- Daily PnL Bar Chart --

interface DailyPnLRow {
  date: string;
  net_pnl_cents: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
}

function DailyPnLChart({ data }: { data: DailyPnLRow[] }) {
  const formatted = data.map((d) => ({
    ...d,
    pnl: d.net_pnl_cents / 100,
    label: new Date(d.date + 'T00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={formatted}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
        <XAxis dataKey="label" tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} />
        <YAxis tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} tickFormatter={(v: number) => `$${v}`} width={45} />
        <ReferenceLine y={0} stroke="rgba(255,255,255,0.1)" />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={((v: number) => [`$${safeFixed(v, 2)}`, 'Net P&L']) as AnyFormatter}
          labelFormatter={(l) => String(l)}
          labelStyle={{ color: GREEN_DIM }}
        />
        <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
          {formatted.map((d, i) => (
            <Cell key={i} fill={d.pnl >= 0 ? GREEN : RED} fillOpacity={0.8} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// -- Strategy Performance --

interface StrategyPerfRow {
  strategy: string;
  total_trades: number;
  wins: number;
  losses: number;
  total_pnl_cents: number;
  win_rate: number;
  avg_pnl_cents: number;
}

function StrategyPerfChart({ data }: { data: StrategyPerfRow[] }) {
  const formatted = data.map((d) => ({
    ...d,
    name: formatStrategyName(d.strategy).slice(0, 12),
    pnl: d.total_pnl_cents / 100,
    avgPnl: (d.avg_pnl_cents ?? 0) / 100,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={formatted} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
        <XAxis type="number" tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} tickFormatter={(v: number) => `$${v}`} />
        <YAxis type="category" dataKey="name" tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} width={90} />
        <ReferenceLine x={0} stroke="rgba(255,255,255,0.1)" />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={((v: number, name: string) => [
            `$${safeFixed(v, 2)}`,
            name === 'pnl' ? 'Total P&L' : 'Avg P&L',
          ]) as AnyFormatter}
          labelStyle={{ color: GREEN_DIM }}
        />
        <Bar dataKey="pnl" radius={[0, 2, 2, 0]}>
          {formatted.map((d, i) => (
            <Cell key={i} fill={stratColor(d.strategy)} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// -- Win Rate Trend --

interface WinRateRow {
  updated_at: string;
  rolling_win_rate: number;
  cumulative_pnl_cents: number;
  cumulative_trades: number;
}

function WinRateChart({ data }: { data: WinRateRow[] }) {
  const formatted = data.map((d, i) => ({
    idx: i + 1,
    wr: d.rolling_win_rate,
    pnl: d.cumulative_pnl_cents / 100,
    trades: d.cumulative_trades,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={formatted}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
        <XAxis dataKey="idx" tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} label={{ value: 'Trade #', fill: GREEN_DIM, fontSize: 9, position: 'insideBottom', offset: -5 }} />
        <YAxis tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} tickFormatter={(v: number) => `${v}%`} width={40} domain={[0, 100]} />
        <ReferenceLine y={50} stroke={AMBER} strokeDasharray="3 3" strokeOpacity={0.5} label={{ value: '50%', fill: AMBER, fontSize: 8, position: 'insideTopRight' }} />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={((v: number, name: string) => [
            name === 'wr' ? `${safeFixed(v, 1)}%` : `$${safeFixed(v, 2)}`,
            name === 'wr' ? 'Win Rate' : 'Cumulative P&L',
          ]) as AnyFormatter}
          labelFormatter={(l) => `Trade #${l}`}
          labelStyle={{ color: GREEN_DIM }}
        />
        <YAxis yAxisId="right" orientation="right" tick={{ fill: CYAN, fontSize: 8 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${v}`} width={40} />
        <Line type="monotone" dataKey="wr" stroke={GREEN} strokeWidth={2} dot={false} activeDot={{ r: 3, fill: GREEN }} />
        <Line type="monotone" dataKey="pnl" stroke={CYAN} strokeWidth={1} dot={false} strokeDasharray="4 2" yAxisId="right" />
      </LineChart>
    </ResponsiveContainer>
  );
}

// -- Regime Timeline --

interface RegimeRow {
  timestamp: string;
  regime: string;
  confidence: number;
  volatility: number | null;
  source: string;
}

function RegimeChart({ data }: { data: RegimeRow[] }) {
  // Encode regime as numeric for area chart, keep confidence
  const regimes = [...new Set(data.map((d) => d.regime))];
  const formatted = data.map((d) => ({
    time: new Date(d.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit' }),
    regime: d.regime,
    confidence: +(d.confidence * 100).toFixed(1),
    regimeIdx: regimes.indexOf(d.regime),
    volatility: d.volatility != null ? +(d.volatility * 100).toFixed(1) : null,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={formatted}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
        <XAxis dataKey="time" tick={{ fill: GREEN_DIM, fontSize: 8 }} tickLine={false} axisLine={{ stroke: AXIS }} interval="preserveStartEnd" />
        <YAxis tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} tickFormatter={(v: number) => `${v}%`} width={35} domain={[0, 100]} />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={((v: number, name: string) => [
            `${v}%`,
            name === 'confidence' ? 'Confidence' : 'Volatility',
          ]) as AnyFormatter}
          labelStyle={{ color: GREEN_DIM }}
        />
        <defs>
          <linearGradient id="regimeGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={GREEN} stopOpacity={0.3} />
            <stop offset="100%" stopColor={GREEN} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <Area
          type="stepAfter"
          dataKey="confidence"
          stroke={GREEN}
          fill="url(#regimeGradient)"
          strokeWidth={1.5}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// -- Trade Scatter --

interface TradeScatterRow {
  updated_at: string;
  strategy: string;
  pnl_cents: number;
  market_ticker: string;
  contracts: number;
}

function TradeScatterChart({ data }: { data: TradeScatterRow[] }) {
  const formatted = data.map((d, i) => ({
    idx: i + 1,
    pnl: d.pnl_cents / 100,
    strategy: d.strategy,
    ticker: d.market_ticker,
    size: Math.max(20, Math.min(200, Math.abs(d.pnl_cents) / 2)),
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ScatterChart>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
        <XAxis dataKey="idx" tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} name="Trade #" />
        <YAxis tick={{ fill: GREEN_DIM, fontSize: 9 }} tickLine={false} axisLine={{ stroke: AXIS }} tickFormatter={(v: number) => `$${v}`} width={45} name="P&L" />
        <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={((v: number, name: string) => [
            name === 'pnl' ? `$${safeFixed(v, 2)}` : String(v),
            name === 'pnl' ? 'P&L' : name,
          ]) as AnyFormatter}
          labelStyle={{ color: GREEN_DIM }}
        />
        <Scatter data={formatted} fill={GREEN}>
          {formatted.map((d, i) => (
            <Cell key={i} fill={d.pnl >= 0 ? GREEN : RED} fillOpacity={0.7} />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  );
}

// -- Fitness Heatmap (CSS grid, not recharts) --

interface FitnessRow {
  strategy_name: string;
  regime: string;
  fitness_score: number;
  trade_count: number;
  total_pnl_cents: number;
}

function FitnessHeatmap({ data }: { data: FitnessRow[] }) {
  const strategies = [...new Set(data.map((d) => d.strategy_name))];
  const regimes = [...new Set(data.map((d) => d.regime))];

  const lookup = new Map<string, FitnessRow>();
  for (const d of data) {
    lookup.set(`${d.strategy_name}|${d.regime}`, d);
  }

  function cellColor(score: number): string {
    if (score >= 0.7) return 'rgba(0, 255, 65, 0.6)';
    if (score >= 0.5) return 'rgba(0, 255, 65, 0.25)';
    if (score >= 0.3) return 'rgba(255, 191, 0, 0.25)';
    return 'rgba(255, 0, 0, 0.2)';
  }

  if (strategies.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-[10px] text-terminal-dim">
        NO FITNESS DATA YET
      </div>
    );
  }

  return (
    <div className="overflow-auto h-full">
      <table className="w-full text-[9px]">
        <thead>
          <tr>
            <th className="text-left px-2 py-1 text-terminal-dim font-normal sticky left-0 bg-terminal-bg-panel">
              STRATEGY
            </th>
            {regimes.map((r, ri) => (
              <th key={`rh-${ri}`} className="text-center px-2 py-1 font-normal" style={{ color: regimeColor(r) }}>
                {formatStrategyName(r).slice(0, 10)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {strategies.map((s, si) => (
            <tr key={`s-${si}`} className="border-t border-terminal-green/5">
              <td className="text-left px-2 py-1.5 text-terminal-green-dim font-semibold tracking-wide sticky left-0 bg-terminal-bg-panel">
                {formatStrategyName(s).slice(0, 14)}
              </td>
              {regimes.map((r, ri) => {
                const cell = lookup.get(`${s}|${r}`);
                if (!cell) {
                  return (
                    <td key={`${si}-${ri}`} className="text-center px-2 py-1.5 text-terminal-dim/30">
                      --
                    </td>
                  );
                }
                return (
                  <td
                    key={`${si}-${ri}`}
                    className="text-center px-2 py-1.5 tabular-nums"
                    style={{ background: cellColor(cell.fitness_score) }}
                    title={`${(cell.fitness_score * 100).toFixed(0)}% fitness | ${cell.trade_count} trades | $${(cell.total_pnl_cents / 100).toFixed(2)} PnL`}
                  >
                    <span className="text-terminal-green font-bold">
                      {(cell.fitness_score * 100).toFixed(0)}
                    </span>
                    <span className="text-terminal-dim ml-0.5">
                      ({cell.trade_count})
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
