'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import type {
  DashboardState,
  Trade,
  CaptainsLogEntry,
  StrategyStatus,
  DailyReview,
} from '@/lib/types';
import {
  centsToUSD,
  shortTime,
  shortDate,
  stripMarkdown,
  truncateNote,
  healthDot,
  healthLabel,
  healthColor,
  formatStrategyName,
} from '@/lib/format';

// ---------------------------------------------------------------------------
// Grade display maps (used by daily reviews)
// ---------------------------------------------------------------------------

const gradeColor: Record<string, string> = {
  A: 'text-terminal-green',
  B: 'text-terminal-cyan',
  C: 'text-terminal-amber',
  D: 'text-terminal-red-dim',
  F: 'text-terminal-red',
};

const gradeBg: Record<string, string> = {
  A: 'bg-terminal-green/10 border-terminal-green/30',
  B: 'bg-terminal-cyan/10 border-terminal-cyan/30',
  C: 'bg-terminal-amber/10 border-terminal-amber/30',
  D: 'bg-terminal-red/5 border-terminal-red/20',
  F: 'bg-terminal-red/10 border-terminal-red/30',
};

function statusLabel(s: StrategyStatus): string {
  if (!s.enabled) return 'DISABLED';
  if (s.auto_disabled) return 'AUTO-OFF';
  if (s.status === 'error') return 'ERROR';
  if (s.status === 'active' || s.status === 'scanning') return 'ACTIVE';
  return 'IDLE';
}

function statusColor(s: StrategyStatus): string {
  if (!s.enabled || s.auto_disabled) return 'text-terminal-dim';
  if (s.status === 'error') return 'text-terminal-red';
  if (s.status === 'active' || s.status === 'scanning') return 'text-terminal-green';
  return 'text-terminal-amber';
}

// ---------------------------------------------------------------------------
// Sort types
// ---------------------------------------------------------------------------
type SortKey =
  | 'name'
  | 'win_rate'
  | 'confidence'
  | 'ev'
  | 'trades'
  | 'health'
  | 'status';

type SortDir = 'asc' | 'desc';

function comparator(key: SortKey, dir: SortDir) {
  const m = dir === 'asc' ? 1 : -1;
  return (a: StrategyStatus, b: StrategyStatus): number => {
    switch (key) {
      case 'name':
        return m * a.name.localeCompare(b.name);
      case 'win_rate':
        return m * ((a.blended_win_rate ?? -1) - (b.blended_win_rate ?? -1));
      case 'confidence':
        return m * ((a.learning_confidence ?? -1) - (b.learning_confidence ?? -1));
      case 'ev':
        return m * ((a.blended_ev_cents ?? -Infinity) - (b.blended_ev_cents ?? -Infinity));
      case 'trades':
        return m * ((a.effective_trades ?? 0) - (b.effective_trades ?? 0));
      case 'health': {
        const order: Record<string, number> = { healthy: 3, warning: 2, critical: 1, unknown: 0 };
        return m * ((order[a.health_status ?? 'unknown'] ?? 0) - (order[b.health_status ?? 'unknown'] ?? 0));
      }
      case 'status': {
        const sOrder = (s: StrategyStatus) => {
          if (s.status === 'error') return 3;
          if (s.status === 'active' || s.status === 'scanning') return 2;
          if (s.enabled) return 1;
          return 0;
        };
        return m * (sOrder(a) - sOrder(b));
      }
      default:
        return 0;
    }
  };
}

// ---------------------------------------------------------------------------
// Per-strategy computed stats from trades
// ---------------------------------------------------------------------------
interface StrategyTradeStats {
  total: number;
  wins: number;
  losses: number;
  pnl_cents: number;
}

function computeTradeStats(trades: Trade[]): Record<string, StrategyTradeStats> {
  const map: Record<string, StrategyTradeStats> = {};
  for (const t of trades) {
    if (!t.strategy) continue;
    if (!map[t.strategy]) map[t.strategy] = { total: 0, wins: 0, losses: 0, pnl_cents: 0 };
    const s = map[t.strategy];
    if (t.status === 'closed' || t.pnl_cents != null) {
      s.total++;
      if ((t.pnl_cents ?? 0) > 0) s.wins++;
      else if ((t.pnl_cents ?? 0) < 0) s.losses++;
      s.pnl_cents += t.pnl_cents ?? 0;
    }
  }
  return map;
}

// ---------------------------------------------------------------------------
// Regime entry parsed from captain's log
// ---------------------------------------------------------------------------
interface RegimeEntry {
  id: string;
  timestamp: string;
  regime: string;
  confidence: number | null;
  content: string;
}

function parseRegimeEntries(entries: CaptainsLogEntry[]): RegimeEntry[] {
  return entries
    .filter((e) => e.regime != null && e.regime !== '')
    .map((e) => ({
      id: e.id,
      timestamp: e.created_at,
      regime: e.regime!,
      confidence: null, // confidence not in the schema directly; could be parsed from content
      content: e.content,
    }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function IntelligencePage() {
  // ---- state ----
  const [status, setStatus] = useState<DashboardState | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [logEntries, setLogEntries] = useState<CaptainsLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // Daily reviews
  const [dailyReviews, setDailyReviews] = useState<DailyReview[]>([]);
  const [expandedReview, setExpandedReview] = useState<string | null>(null);

  // Table state
  const [sortKey, setSortKey] = useState<SortKey>('win_rate');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  // ---- fetchers ----
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/status');
      if (res.ok) setStatus(await res.json());
    } catch {
      /* silent */
    }
  }, []);

  const fetchTrades = useCallback(async () => {
    try {
      const res = await fetch('/api/trades?limit=500');
      if (res.ok) {
        const d = await res.json();
        setTrades(d.trades || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  const fetchLog = useCallback(async () => {
    try {
      const res = await fetch('/api/captains-log?limit=50');
      if (res.ok) {
        const d = await res.json();
        setLogEntries(d.entries || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  const fetchReviews = useCallback(async () => {
    try {
      const res = await fetch('/api/daily-reviews?days=14');
      if (res.ok) {
        const d = await res.json();
        setDailyReviews(d.reviews || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  // ---- initial load ----
  useEffect(() => {
    (async () => {
      await Promise.all([fetchStatus(), fetchTrades(), fetchLog(), fetchReviews()]);
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- polling every 60s ----
  useEffect(() => {
    const interval = setInterval(() => {
      fetchStatus();
      fetchTrades();
      fetchLog();
      fetchReviews();
    }, 60_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- derived data ----
  const strategies = status?.strategies ?? [];

  const sorted = useMemo(
    () => [...strategies].sort(comparator(sortKey, sortDir)),
    [strategies, sortKey, sortDir],
  );

  const tradeStats = useMemo(() => computeTradeStats(trades), [trades]);

  const regimeHistory = useMemo(() => parseRegimeEntries(logEntries), [logEntries]);

  // Sort handler
  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const sortArrow = (key: SortKey) => {
    if (sortKey !== key) return '';
    return sortDir === 'asc' ? ' ^' : ' v';
  };

  // Recent trades for expanded row
  const tradesForStrategy = (name: string): Trade[] => {
    return trades
      .filter((t) => t.strategy === name)
      .slice(0, 10);
  };

  // ---- loading ----
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-lg terminal-glow-bright">
          INTELLIGENCE<span className="animate-cursor-blink">_</span>
        </div>
      </div>
    );
  }

  // ---- render ----
  return (
    <div className="p-4 md:p-6 max-w-[1600px] mx-auto space-y-6">
      {/* Page header */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          <div className="w-2 h-2 rounded-full bg-terminal-cyan animate-pulse" />
          <span className="text-[10px] text-terminal-cyan tracking-[0.2em] uppercase">
            Intelligence
          </span>
        </div>
        <div className="text-xl md:text-2xl font-bold terminal-glow tracking-wider">
          STRATEGY INTELLIGENCE
        </div>
        <div className="text-[10px] text-terminal-dim mt-1">
          {strategies.length} strategies tracked | {trades.length} trades analyzed | Refresh: 60s
        </div>
      </div>

      {/* ================================================================
          STRATEGY TABLE
         ================================================================ */}
      <div className="panel">
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-terminal-green/20">
                {(
                  [
                    ['name', 'STRATEGY'],
                    ['win_rate', 'WIN RATE'],
                    ['confidence', 'CONFIDENCE'],
                    ['ev', 'EV (CENTS)'],
                    ['trades', 'EFF. TRADES'],
                    ['health', 'HEALTH'],
                    ['status', 'STATUS'],
                  ] as [SortKey, string][]
                ).map(([key, label]) => (
                  <th
                    key={key}
                    onClick={() => handleSort(key)}
                    className={`text-left px-3 py-2.5 font-normal tracking-wider cursor-pointer select-none hover:text-terminal-green transition-colors ${
                      sortKey === key ? 'text-terminal-green' : 'text-terminal-dim'
                    } ${key !== 'name' ? 'text-right' : ''}`}
                  >
                    {label}
                    {sortArrow(key)}
                  </th>
                ))}
              </tr>
            </thead>
              {sorted.map((s) => {
                const isExpanded = expandedRow === s.name;
                const rowTrades = isExpanded ? tradesForStrategy(s.name) : [];
                const ts = tradeStats[s.name];
                return (
                  <tbody key={s.name}>
                    <tr
                      onClick={() => setExpandedRow(isExpanded ? null : s.name)}
                      className={`border-b border-terminal-green/5 cursor-pointer transition-colors ${
                        isExpanded
                          ? 'bg-terminal-bg-elevated'
                          : 'hover:bg-terminal-bg-elevated/50'
                      }`}
                    >
                      {/* Strategy name */}
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-[10px] text-terminal-dim transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`}
                          >
                            &gt;
                          </span>
                          <span
                            className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${healthDot(
                              s.health_status,
                            )}`}
                          />
                          <span className="text-terminal-green font-semibold tracking-wide">
                            {formatStrategyName(s.name)}
                          </span>
                          {s.auto_disabled && (
                            <span className="badge-red text-[9px] px-1 py-0">
                              AUTO-OFF
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Win Rate */}
                      <td className="px-3 py-2 text-right tabular-nums">
                        {s.blended_win_rate != null ? (
                          <span
                            className={
                              s.blended_win_rate >= 0.5
                                ? 'text-terminal-green'
                                : 'text-terminal-red'
                            }
                          >
                            {(s.blended_win_rate * 100).toFixed(1)}%
                          </span>
                        ) : (
                          <span className="text-terminal-dim">--</span>
                        )}
                      </td>

                      {/* Confidence */}
                      <td className="px-3 py-2 text-right tabular-nums">
                        {s.learning_confidence != null ? (
                          <span className="text-terminal-cyan">
                            {(s.learning_confidence * 100).toFixed(0)}%
                          </span>
                        ) : (
                          <span className="text-terminal-dim">--</span>
                        )}
                      </td>

                      {/* EV */}
                      <td className="px-3 py-2 text-right tabular-nums">
                        {s.blended_ev_cents != null ? (
                          <span
                            className={
                              s.blended_ev_cents >= 0
                                ? 'text-terminal-green'
                                : 'text-terminal-red'
                            }
                          >
                            {s.blended_ev_cents >= 0 ? '+' : ''}
                            {s.blended_ev_cents.toFixed(1)}
                          </span>
                        ) : (
                          <span className="text-terminal-dim">--</span>
                        )}
                      </td>

                      {/* Effective Trades */}
                      <td className="px-3 py-2 text-right tabular-nums text-terminal-cyan-dim">
                        {s.effective_trades ?? 0}
                      </td>

                      {/* Health */}
                      <td className={`px-3 py-2 text-right ${healthColor(s.health_status)}`}>
                        {healthLabel(s.health_status)}
                      </td>

                      {/* Status */}
                      <td className={`px-3 py-2 text-right font-semibold ${statusColor(s)}`}>
                        {statusLabel(s)}
                      </td>
                    </tr>

                    {/* Expanded: recent trades */}
                    {isExpanded && (
                      <tr className="bg-terminal-bg-elevated/80">
                        <td colSpan={7} className="px-3 py-3">
                          <div className="space-y-2">
                            {/* Summary stats from trade data */}
                            {ts && (
                              <div className="flex items-center gap-6 text-[10px] mb-2 pb-2 border-b border-terminal-green/10">
                                <span className="text-terminal-dim">
                                  TRADE STATS:
                                </span>
                                <span>
                                  Total:{' '}
                                  <span className="text-terminal-cyan tabular-nums">
                                    {ts.total}
                                  </span>
                                </span>
                                <span>
                                  W/L:{' '}
                                  <span className="text-terminal-green tabular-nums">
                                    {ts.wins}
                                  </span>
                                  /
                                  <span className="text-terminal-red tabular-nums">
                                    {ts.losses}
                                  </span>
                                </span>
                                <span>
                                  Net:{' '}
                                  <span
                                    className={`tabular-nums ${
                                      ts.pnl_cents >= 0
                                        ? 'text-terminal-green'
                                        : 'text-terminal-red'
                                    }`}
                                  >
                                    {centsToUSD(ts.pnl_cents)}
                                  </span>
                                </span>
                              </div>
                            )}

                            {/* Disabled reason */}
                            {s.disabled_reason && (
                              <div className="text-[10px] text-terminal-amber mb-2">
                                Disabled: {s.disabled_reason}
                                {s.disabled_at && (
                                  <span className="text-terminal-dim ml-2">
                                    ({shortDate(s.disabled_at)})
                                  </span>
                                )}
                              </div>
                            )}

                            {/* Recent trades */}
                            <div className="text-[9px] text-terminal-dim mb-1 tracking-wider">
                              RECENT TRADES
                            </div>
                            {rowTrades.length === 0 ? (
                              <div className="text-[10px] text-terminal-dim">
                                No trades recorded for this strategy.
                              </div>
                            ) : (
                              <table className="w-full text-[10px]">
                                <thead>
                                  <tr className="text-terminal-dim">
                                    <th className="text-left pr-3 py-1 font-normal">
                                      TIME
                                    </th>
                                    <th className="text-left pr-3 py-1 font-normal">
                                      TICKER
                                    </th>
                                    <th className="text-left pr-3 py-1 font-normal">
                                      ACTION
                                    </th>
                                    <th className="text-right pr-3 py-1 font-normal">
                                      QTY
                                    </th>
                                    <th className="text-right pr-3 py-1 font-normal">
                                      ENTRY
                                    </th>
                                    <th className="text-right py-1 font-normal">
                                      P&amp;L
                                    </th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {rowTrades.map((t) => (
                                    <tr
                                      key={t.id}
                                      className="border-t border-terminal-green/5"
                                    >
                                      <td className="pr-3 py-1 text-terminal-cyan-dim tabular-nums">
                                        {shortDate(t.created_at)}
                                      </td>
                                      <td className="pr-3 py-1 text-terminal-green">
                                        {t.market_ticker}
                                      </td>
                                      <td className="pr-3 py-1 uppercase text-terminal-amber">
                                        {t.action}
                                      </td>
                                      <td className="pr-3 py-1 text-right tabular-nums">
                                        {t.contracts}
                                      </td>
                                      <td className="pr-3 py-1 text-right tabular-nums text-terminal-dim">
                                        {t.entry_price_cents}c
                                      </td>
                                      <td
                                        className={`py-1 text-right tabular-nums font-semibold ${
                                          (t.pnl_cents ?? 0) >= 0
                                            ? 'text-terminal-green'
                                            : 'text-terminal-red'
                                        }`}
                                      >
                                        {t.pnl_cents != null
                                          ? centsToUSD(t.pnl_cents)
                                          : '--'}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </tbody>
                );
              })}
          </table>
        </div>
      </div>

      {/* ================================================================
          REGIME HISTORY
         ================================================================ */}
      <div className="panel">
        <div className="flex items-center justify-between px-3 py-2 border-b border-terminal-green/20">
          <span className="text-[10px] font-bold tracking-[0.15em] terminal-glow">
            REGIME HISTORY
          </span>
          <span className="text-[10px] text-terminal-dim">
            {regimeHistory.length} transitions
          </span>
        </div>
        <div className="p-3">
          {regimeHistory.length === 0 ? (
            <div className="text-[10px] text-terminal-dim py-4 text-center">
              NO REGIME TRANSITIONS RECORDED
            </div>
          ) : (
            <div className="space-y-0">
              {/* Current regime highlighted */}
              <div className="flex items-center gap-3 mb-3 p-2 rounded border border-terminal-cyan/20 bg-terminal-cyan/5">
                  <span className="text-[9px] text-terminal-dim tracking-wider">
                    CURRENT:
                  </span>
                  <span className="text-sm text-terminal-cyan font-bold tracking-wide terminal-glow">
                    {formatStrategyName(regimeHistory[0].regime)}
                  </span>
                  <span className="text-[10px] text-terminal-cyan-dim tabular-nums">
                    since {shortDate(regimeHistory[0].timestamp)}
                  </span>
                </div>

              {/* Timeline */}
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="text-terminal-dim border-b border-terminal-green/10">
                    <th className="text-left px-2 py-1.5 font-normal tracking-wider">
                      TIME
                    </th>
                    <th className="text-left px-2 py-1.5 font-normal tracking-wider">
                      REGIME
                    </th>
                    <th className="text-left px-2 py-1.5 font-normal tracking-wider">
                      NOTES
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-terminal-green/5">
                  {regimeHistory.map((r, i) => (
                    <tr
                      key={r.id}
                      className={`transition-colors ${
                        i === 0
                          ? 'bg-terminal-cyan/5'
                          : 'hover:bg-terminal-bg-elevated/50'
                      }`}
                    >
                      <td className="px-2 py-1.5 text-terminal-cyan-dim tabular-nums whitespace-nowrap">
                        {shortDate(r.timestamp)}
                      </td>
                      <td className="px-2 py-1.5 text-terminal-cyan font-semibold tracking-wide">
                        {formatStrategyName(r.regime)}
                      </td>
                      <td
                        className="px-2 py-1.5 text-terminal-dim whitespace-nowrap overflow-hidden text-ellipsis max-w-[300px]"
                        title={stripMarkdown(r.content)}
                      >
                        {truncateNote(r.content)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ================================================================
          AI DAILY REVIEWS
         ================================================================ */}
      <div className="panel">
        <div className="flex items-center justify-between px-3 py-2 border-b border-terminal-green/20">
          <span className="text-[10px] font-bold tracking-[0.15em] terminal-glow">
            AI DAILY REVIEWS
          </span>
          <span className="text-[10px] text-terminal-dim">
            {dailyReviews.length} days with activity
          </span>
        </div>

        {dailyReviews.length === 0 ? (
          <div className="text-[10px] text-terminal-dim py-6 text-center">
            NO TRADING DAYS RECORDED YET
          </div>
        ) : (
          <div className="divide-y divide-terminal-green/5">
            {dailyReviews.map((review) => {
              const isExpanded = expandedReview === review.date;
              const pnlPositive = review.net_pnl_cents >= 0;

              return (
                <div key={review.date}>
                  {/* Summary row */}
                  <button
                    onClick={() =>
                      setExpandedReview(isExpanded ? null : review.date)
                    }
                    className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors ${
                      isExpanded
                        ? 'bg-terminal-bg-elevated'
                        : 'hover:bg-terminal-bg-elevated/50'
                    }`}
                  >
                    {/* Expand chevron */}
                    <span
                      className={`text-[10px] text-terminal-dim transition-transform duration-200 ${
                        isExpanded ? 'rotate-90' : ''
                      }`}
                    >
                      &gt;
                    </span>

                    {/* Grade badge */}
                    <span
                      className={`text-sm font-black w-7 h-7 flex items-center justify-center rounded border ${
                        gradeBg[review.grade]
                      } ${gradeColor[review.grade]}`}
                    >
                      {review.grade}
                    </span>

                    {/* Date */}
                    <span className="text-[10px] text-terminal-cyan-dim tabular-nums w-20">
                      {new Date(review.date + 'T12:00:00').toLocaleDateString(
                        'en-US',
                        { month: 'short', day: 'numeric', weekday: 'short' },
                      )}
                    </span>

                    {/* PnL */}
                    <span
                      className={`text-[11px] font-bold tabular-nums w-20 text-right ${
                        pnlPositive ? 'text-terminal-green' : 'text-terminal-red'
                      }`}
                    >
                      {pnlPositive ? '+' : ''}
                      ${(review.net_pnl_cents / 100).toFixed(2)}
                    </span>

                    {/* Win Rate */}
                    <span className="text-[10px] tabular-nums text-terminal-dim w-12 text-right">
                      {(review.win_rate * 100).toFixed(0)}% WR
                    </span>

                    {/* Trades */}
                    <span className="text-[10px] tabular-nums text-terminal-dim w-10 text-right">
                      {review.total_trades}T
                    </span>

                    {/* Regime */}
                    {review.regime && (
                      <span className="text-[9px] text-terminal-cyan tracking-wide hidden sm:inline ml-auto">
                        {formatStrategyName(review.regime!)}
                      </span>
                    )}
                  </button>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div className="px-3 py-3 bg-terminal-bg-elevated/80 space-y-3">
                      {/* Grade reasons */}
                      <div className="flex flex-wrap gap-2">
                        {review.grade_reasons.map((reason, i) => (
                          <span
                            key={i}
                            className="text-[9px] text-terminal-dim px-2 py-0.5 rounded border border-terminal-green/10 bg-terminal-bg"
                          >
                            {reason}
                          </span>
                        ))}
                      </div>

                      {/* Stats grid */}
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        <div className="text-center p-2 rounded border border-terminal-green/10 bg-terminal-bg">
                          <div className="text-[9px] text-terminal-dim tracking-wider">
                            TRADES
                          </div>
                          <div className="text-sm font-bold text-terminal-cyan tabular-nums">
                            {review.total_trades}
                          </div>
                        </div>
                        <div className="text-center p-2 rounded border border-terminal-green/10 bg-terminal-bg">
                          <div className="text-[9px] text-terminal-dim tracking-wider">
                            W / L
                          </div>
                          <div className="text-sm font-bold tabular-nums">
                            <span className="text-terminal-green">
                              {review.winning_trades}
                            </span>
                            <span className="text-terminal-dim mx-1">/</span>
                            <span className="text-terminal-red">
                              {review.losing_trades}
                            </span>
                          </div>
                        </div>
                        <div className="text-center p-2 rounded border border-terminal-green/10 bg-terminal-bg">
                          <div className="text-[9px] text-terminal-dim tracking-wider">
                            NET P&L
                          </div>
                          <div
                            className={`text-sm font-bold tabular-nums ${
                              pnlPositive
                                ? 'text-terminal-green'
                                : 'text-terminal-red'
                            }`}
                          >
                            {pnlPositive ? '+' : ''}$
                            {(review.net_pnl_cents / 100).toFixed(2)}
                          </div>
                        </div>
                        <div className="text-center p-2 rounded border border-terminal-green/10 bg-terminal-bg">
                          <div className="text-[9px] text-terminal-dim tracking-wider">
                            WIN RATE
                          </div>
                          <div
                            className={`text-sm font-bold tabular-nums ${
                              review.win_rate >= 0.5
                                ? 'text-terminal-green'
                                : 'text-terminal-red'
                            }`}
                          >
                            {(review.win_rate * 100).toFixed(1)}%
                          </div>
                        </div>
                      </div>

                      {/* Best / Worst trades */}
                      {(review.best_trade || review.worst_trade) && (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {review.best_trade && (
                            <div className="flex items-center gap-2 p-2 rounded border border-terminal-green/20 bg-terminal-green/5">
                              <span className="text-[9px] text-terminal-dim tracking-wider">
                                BEST:
                              </span>
                              <span className="text-[10px] text-terminal-green font-semibold">
                                {review.best_trade.ticker}
                              </span>
                              <span className="text-[10px] text-terminal-green font-bold tabular-nums ml-auto">
                                +$
                                {(review.best_trade.pnl_cents / 100).toFixed(2)}
                              </span>
                            </div>
                          )}
                          {review.worst_trade && (
                            <div className="flex items-center gap-2 p-2 rounded border border-terminal-red/20 bg-terminal-red/5">
                              <span className="text-[9px] text-terminal-dim tracking-wider">
                                WORST:
                              </span>
                              <span className="text-[10px] text-terminal-red font-semibold">
                                {review.worst_trade.ticker}
                              </span>
                              <span className="text-[10px] text-terminal-red font-bold tabular-nums ml-auto">
                                -$
                                {(
                                  Math.abs(review.worst_trade.pnl_cents) / 100
                                ).toFixed(2)}
                              </span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Strategy breakdown */}
                      {review.strategy_breakdown.length > 0 && (
                        <div>
                          <div className="text-[9px] text-terminal-dim tracking-wider mb-1.5">
                            STRATEGY BREAKDOWN
                          </div>
                          <div className="space-y-1">
                            {review.strategy_breakdown.map((s) => (
                              <div
                                key={s.name}
                                className="flex items-center gap-3 text-[10px]"
                              >
                                <span className="text-terminal-green font-semibold tracking-wide w-32 truncate">
                                  {formatStrategyName(s.name)}
                                </span>
                                <span className="text-terminal-dim tabular-nums">
                                  {s.trades}T
                                </span>
                                <span className="text-terminal-dim tabular-nums">
                                  {s.wins}W
                                </span>
                                <span
                                  className={`tabular-nums font-semibold ml-auto ${
                                    s.pnl_cents >= 0
                                      ? 'text-terminal-green'
                                      : 'text-terminal-red'
                                  }`}
                                >
                                  {s.pnl_cents >= 0 ? '+' : ''}$
                                  {(s.pnl_cents / 100).toFixed(2)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Highlights from captain's log */}
                      {review.highlights.length > 0 && (
                        <div>
                          <div className="text-[9px] text-terminal-dim tracking-wider mb-1.5">
                            BOT HIGHLIGHTS
                          </div>
                          <div className="space-y-1">
                            {review.highlights.map((h, i) => (
                              <div
                                key={i}
                                className="text-[10px] text-terminal-dim pl-2 border-l border-terminal-cyan/20"
                              >
                                {h}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Regime info */}
                      {review.regime && (
                        <div className="flex items-center gap-2 text-[10px]">
                          <span className="text-terminal-dim tracking-wider">
                            REGIME:
                          </span>
                          <span className="text-terminal-cyan font-semibold">
                            {formatStrategyName(review.regime!)}
                          </span>
                          {review.regime_changes > 1 && (
                            <span className="text-terminal-amber text-[9px]">
                              ({review.regime_changes} transitions)
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-terminal-green/10 pt-3 flex justify-between items-center text-[10px] text-terminal-dim">
        <span>INTELLIGENCE VIEW</span>
        <span>
          {strategies.length} strategies | {trades.length} trades loaded
        </span>
      </div>
    </div>
  );
}
