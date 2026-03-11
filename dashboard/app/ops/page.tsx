'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import AnalyticsPanel from '@/components/AnalyticsPanel';
import StrategiesPanel from '@/components/StrategiesPanel';
import WeatherMap from '@/components/WeatherMap';
import type {
  DashboardState,
  Position,
  Order,
  BotConfig,
  CaptainsLogEntry,
} from '@/lib/types';
import { centsToUSD, shortTime } from '@/lib/format';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pctString(n: number): string {
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`;
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

function logPriorityColor(p: CaptainsLogEntry['priority']): string {
  switch (p) {
    case 'critical': return 'text-terminal-red';
    case 'significant': return 'text-terminal-amber';
    default: return 'text-terminal-green-dim';
  }
}

const RISK_TIERS = [
  { min: 80, color: 'var(--terminal-red)', glow: '0 0 4px rgba(255,0,0,0.8)' },
  { min: 50, color: 'var(--terminal-amber)', glow: '0 0 4px rgba(255,191,0,0.8)' },
  { min: 0, color: 'var(--terminal-green)', glow: '0 0 4px rgba(0,255,65,0.8)' },
] as const;

function riskTier(pct: number): typeof RISK_TIERS[number] {
  return RISK_TIERS.find((t) => pct > t.min) ?? RISK_TIERS[RISK_TIERS.length - 1];
}

// ---------------------------------------------------------------------------
// Balance history type (matches /api/performance response)
// ---------------------------------------------------------------------------
interface BalanceSnapshot {
  timestamp: string;
  balance_cents: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CommandCenter() {
  // ---- state ----
  const [status, setStatus] = useState<DashboardState | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [balanceHistory, setBalanceHistory] = useState<BalanceSnapshot[]>([]);
  const [config, setConfig] = useState<BotConfig | null>(null);
  const [logEntries, setLogEntries] = useState<CaptainsLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // Optimistic toggle tracking
  const [pendingToggles, setPendingToggles] = useState<
    Record<string, { enabled: boolean; at: number }>
  >({});

  // ---- fetchers ----
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) return;
      const data: DashboardState = await res.json();

      // Apply pending overrides
      const now = Date.now();
      const TTL = 10_000;
      const still: typeof pendingToggles = {};
      if (data.strategies && Object.keys(pendingToggles).length > 0) {
        data.strategies = data.strategies.map((s) => {
          const ov = pendingToggles[s.name];
          if (ov && now - ov.at < TTL) {
            still[s.name] = ov;
            return { ...s, enabled: ov.enabled };
          }
          return s;
        });
        setPendingToggles(still);
      }
      setStatus(data);
    } catch {
      /* silent */
    }
  }, [pendingToggles]);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await fetch('/api/positions');
      if (res.ok) {
        const d = await res.json();
        setPositions(d.positions || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  const fetchOrders = useCallback(async () => {
    try {
      const res = await fetch('/api/orders');
      if (res.ok) {
        const d = await res.json();
        setOrders(d.orders || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  const fetchPerformance = useCallback(async () => {
    try {
      const res = await fetch('/api/performance?limit=500');
      if (res.ok) {
        const d = await res.json();
        setBalanceHistory(d.history || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch('/api/config');
      if (res.ok) {
        const d = await res.json();
        setConfig(d.config || null);
      }
    } catch {
      /* silent */
    }
  }, []);

  const fetchLog = useCallback(async () => {
    try {
      const res = await fetch('/api/captains-log?limit=20');
      if (res.ok) {
        const d = await res.json();
        setLogEntries(d.entries || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  // ---- initial load ----
  useEffect(() => {
    (async () => {
      await Promise.all([
        fetchStatus(),
        fetchPositions(),
        fetchOrders(),
        fetchPerformance(),
        fetchConfig(),
        fetchLog(),
      ]);
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- polling ----
  useEffect(() => {
    const fast = setInterval(() => {
      fetchStatus();
      fetchPositions();
      fetchOrders();
      fetchConfig();
      fetchLog();
    }, 10_000);
    const slow = setInterval(fetchPerformance, 30_000);
    return () => {
      clearInterval(fast);
      clearInterval(slow);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- derived data ----
  const strategies = status?.strategies ?? [];

  const dailyChange = useMemo(() => {
    if (balanceHistory.length < 2) return { cents: 0, pct: 0 };
    const todayStr = new Date().toLocaleDateString('en-CA');
    const today = balanceHistory.filter(
      (e) => new Date(e.timestamp).toLocaleDateString('en-CA') === todayStr,
    );
    if (today.length < 2) return { cents: 0, pct: 0 };
    // API returns newest-first (ORDER BY timestamp.desc)
    const latest = today[0].balance_cents;
    const earliest = today[today.length - 1].balance_cents;
    const c = latest - earliest;
    return { cents: c, pct: earliest > 0 ? (c / earliest) * 100 : 0 };
  }, [balanceHistory]);

  const blendedWinRate = useMemo(() => {
    const withData = strategies.filter(
      (s) => s.blended_win_rate != null && (s.effective_trades ?? 0) > 0,
    );
    if (withData.length === 0) return 0;
    let ws = 0;
    let tw = 0;
    for (const s of withData) {
      const w = s.effective_trades ?? 1;
      ws += (s.blended_win_rate ?? 0) * w;
      tw += w;
    }
    return tw > 0 ? (ws / tw) * 100 : 0;
  }, [strategies]);

  const riskPct = useMemo(() => {
    if (!status?.risk) return 0;
    const { daily_loss_used_cents, daily_loss_limit_cents } = status.risk;
    return daily_loss_limit_cents > 0
      ? (daily_loss_used_cents / daily_loss_limit_cents) * 100
      : 0;
  }, [status?.risk]);

  // ---- toggle handler ----
  const handleToggle = useCallback(
    (name: string, enabled: boolean) => {
      // Optimistic update
      if (status) {
        setStatus({
          ...status,
          strategies: status.strategies.map((s) =>
            s.name === name ? { ...s, enabled } : s,
          ),
        });
      }
      setPendingToggles((prev) => ({
        ...prev,
        [name]: { enabled, at: Date.now() },
      }));
      fetch('/api/strategies/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: name, enabled }),
      }).catch(() => {});
    },
    [status],
  );

  // ---- loading state ----
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-lg terminal-glow-bright">
          COMMAND CENTER<span className="animate-cursor-blink">_</span>
        </div>
      </div>
    );
  }

  // ---- render ----
  return (
    <div className="p-4 md:p-6 max-w-[1600px] mx-auto space-y-4">
      {/* ================================================================
          TOP BAR — Key Metrics
         ================================================================ */}
      <div className="grid grid-cols-3 lg:grid-cols-5 gap-1.5 sm:gap-2 md:gap-3">
        {/* Balance */}
        <div className="panel p-2 sm:p-3">
          <div className="text-[9px] sm:text-[10px] hierarchy-label tracking-[0.15em] mb-1">
            BALANCE
          </div>
          <div className="text-sm sm:text-lg md:text-xl hierarchy-primary tabular-nums leading-tight">
            {centsToUSD(status?.account.balance_cents ?? 0)}
          </div>
        </div>

        {/* Daily P&L */}
        <div className="panel p-2 sm:p-3">
          <div className="text-[9px] sm:text-[10px] hierarchy-label tracking-[0.15em] mb-1">
            DAILY P&amp;L
          </div>
          <div
            className={`text-sm sm:text-lg md:text-xl tabular-nums leading-tight font-bold ${
              dailyChange.cents >= 0 ? 'text-terminal-green' : 'text-terminal-red'
            }`}
            style={{
              textShadow:
                dailyChange.cents >= 0
                  ? '0 0 4px rgba(0,255,65,0.8)'
                  : '0 0 4px rgba(255,0,0,0.8)',
            }}
          >
            {dailyChange.cents >= 0 ? '+' : ''}
            {centsToUSD(dailyChange.cents)}
          </div>
          <div
            className={`text-[9px] sm:text-[10px] tabular-nums ${
              dailyChange.cents >= 0 ? 'text-terminal-green-dim' : 'text-terminal-red-dim'
            }`}
          >
            {pctString(dailyChange.pct)}
          </div>
        </div>

        {/* Active Positions */}
        <div className="panel p-2 sm:p-3">
          <div className="text-[9px] sm:text-[10px] hierarchy-label tracking-[0.15em] mb-1">
            POSITIONS
          </div>
          <div className="text-sm sm:text-lg md:text-xl hierarchy-primary tabular-nums leading-tight">
            {positions.length}
          </div>
        </div>

        {/* Win Rate */}
        <div className="panel p-2 sm:p-3">
          <div className="text-[9px] sm:text-[10px] hierarchy-label tracking-[0.15em] mb-1">
            WIN RATE
          </div>
          <div className="text-sm sm:text-lg md:text-xl hierarchy-primary tabular-nums leading-tight">
            {blendedWinRate.toFixed(1)}%
          </div>
        </div>

        {/* Risk Used */}
        <div className="panel p-2 sm:p-3">
          <div className="text-[9px] sm:text-[10px] hierarchy-label tracking-[0.15em] mb-1">
            RISK USED
          </div>
          <div className="text-sm sm:text-lg md:text-xl tabular-nums leading-tight font-bold"
            style={{ color: riskTier(riskPct).color, textShadow: riskTier(riskPct).glow }}
          >
            {riskPct.toFixed(0)}%
          </div>
          {/* progress bar */}
          <div className="mt-1 h-1 w-full rounded-full bg-terminal-bg-panel overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(riskPct, 100)}%`,
                background: riskTier(riskPct).color,
              }}
            />
          </div>
        </div>
      </div>

      {/* ================================================================
          MAIN CONTENT — Left 60% + Right 40%
         ================================================================ */}
      <div className="flex flex-col lg:flex-row gap-4">
        {/* -------- LEFT COLUMN (60%) -------- */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* ------ Strategies Panel (regime-driven) ------ */}
          <StrategiesPanel strategies={strategies} onToggle={handleToggle} />

          {/* ------ Market Weather System ------ */}
          <WeatherMap />

          {/* ------ Analytics Panel (multi-view charts) ------ */}
          <AnalyticsPanel />
        </div>

        {/* -------- RIGHT COLUMN (40%) -------- */}
        <div className="lg:w-[40%] shrink-0 space-y-4">
          {/* ------ Captain's Log ------ */}
          <div className="panel flex flex-col max-h-[50vh] lg:max-h-[40vh]">
            <div className="flex items-center justify-between px-3 py-2 border-b border-terminal-green/20 shrink-0">
              <span className="text-[10px] font-bold tracking-[0.15em] terminal-glow">
                CAPTAIN&apos;S LOG
              </span>
              <span className="text-[10px] text-terminal-dim">
                {logEntries.length} ENTRIES
              </span>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
              {logEntries.length === 0 ? (
                <div className="text-[10px] text-terminal-dim py-4 text-center">
                  NO LOG ENTRIES
                </div>
              ) : (
                [...logEntries].reverse().map((entry) => (
                  <div key={entry.id} className="text-[10px] leading-relaxed animate-fade-in">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-terminal-cyan-dim tabular-nums">
                        {shortTime(entry.created_at)}
                      </span>
                      {entry.event_type && (
                        <span className="badge-green text-[9px] px-1 py-0">
                          {entry.event_type}
                        </span>
                      )}
                      {entry.strategy && (
                        <span className="text-terminal-amber text-[9px]">
                          [{entry.strategy}]
                        </span>
                      )}
                    </div>
                    <div className={logPriorityColor(entry.priority)}>
                      {entry.content}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* ------ Positions Table ------ */}
          <div className="panel">
            <div className="flex items-center justify-between px-3 py-2 border-b border-terminal-green/20">
              <span className="text-[10px] font-bold tracking-[0.15em] terminal-glow">
                POSITIONS
              </span>
              <span className="text-[10px] text-terminal-dim">
                {positions.length} OPEN
              </span>
            </div>
            <div className="overflow-x-auto">
              {positions.length === 0 ? (
                <div className="text-[10px] text-terminal-dim py-4 text-center">
                  NO OPEN POSITIONS
                </div>
              ) : (
                <table className="w-full text-[10px]">
                  <thead>
                    <tr className="text-terminal-dim border-b border-terminal-green/10">
                      <th className="text-left px-3 py-1.5 font-normal tracking-wider">
                        TICKER
                      </th>
                      <th className="text-left px-2 py-1.5 font-normal tracking-wider">
                        SIDE
                      </th>
                      <th className="text-right px-2 py-1.5 font-normal tracking-wider">
                        QTY
                      </th>
                      <th className="text-right px-2 py-1.5 font-normal tracking-wider">
                        ENTRY
                      </th>
                      <th className="text-right px-2 py-1.5 font-normal tracking-wider">
                        CURRENT
                      </th>
                      <th className="text-right px-3 py-1.5 font-normal tracking-wider">
                        P&amp;L
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-terminal-green/5">
                    {positions.map((p) => {
                      const pnl = p.realized_pnl ?? 0;
                      return (
                        <tr key={p.id} className="hover:bg-terminal-bg-elevated/50 transition-colors">
                          <td className="px-3 py-1.5 text-terminal-green font-semibold truncate max-w-[120px]">
                            {p.ticker}
                          </td>
                          <td className="px-2 py-1.5 uppercase text-terminal-cyan-dim">
                            {p.side}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums">
                            {p.contracts}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-terminal-dim">
                            {p.avg_entry_price_cents != null
                              ? `${p.avg_entry_price_cents}c`
                              : '--'}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-terminal-dim">
                            {p.current_price != null ? `${p.current_price}c` : '--'}
                          </td>
                          <td
                            className={`px-3 py-1.5 text-right tabular-nums font-semibold ${
                              pnl >= 0 ? 'text-terminal-green' : 'text-terminal-red'
                            }`}
                          >
                            {pnl >= 0 ? '+' : ''}
                            {centsToUSD(pnl)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* ------ Orders (resting only) ------ */}
          {(() => {
            const restingOrders = orders.filter((o) => o.status === 'resting');
            if (restingOrders.length === 0) return null;
            return (
            <div className="panel">
              <div className="flex items-center justify-between px-3 py-2 border-b border-terminal-green/20">
                <span className="text-[10px] font-bold tracking-[0.15em] terminal-glow">
                  RESTING ORDERS
                </span>
                <span className="text-[10px] text-terminal-cyan">
                  {restingOrders.length}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[10px]">
                  <thead>
                    <tr className="text-terminal-dim border-b border-terminal-green/10">
                      <th className="text-left px-3 py-1.5 font-normal tracking-wider">
                        TICKER
                      </th>
                      <th className="text-left px-2 py-1.5 font-normal tracking-wider">
                        SIDE
                      </th>
                      <th className="text-right px-2 py-1.5 font-normal tracking-wider">
                        QTY
                      </th>
                      <th className="text-right px-3 py-1.5 font-normal tracking-wider">
                        PRICE
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-terminal-green/5">
                    {restingOrders.map((o) => (
                        <tr key={o.id} className="hover:bg-terminal-bg-elevated/50 transition-colors">
                          <td className="px-3 py-1.5 text-terminal-green truncate max-w-[120px]">
                            {o.ticker}
                          </td>
                          <td className="px-2 py-1.5 uppercase text-terminal-cyan-dim">
                            {o.action} {o.side}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums">
                            {o.remaining_count}
                          </td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-terminal-dim">
                            {o.yes_price != null ? `${o.yes_price}c` : '--'}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
            );
          })()}
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-terminal-green/10 pt-3 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 text-[10px] text-terminal-dim">
        <div className="flex items-center gap-3">
          <span>COMMAND CENTER</span>
          <span>
            MODE:{' '}
            <span className="text-terminal-amber uppercase">
              {(config?.mode as string) || 'unknown'}
            </span>
          </span>
        </div>
        <div className="flex items-center gap-3">
          {config?.last_heartbeat && (
            <span>
              HEARTBEAT:{' '}
              <span className="text-terminal-cyan-dim">
                {timeAgo(config.last_heartbeat)}
              </span>
            </span>
          )}
          {status?.timestamp && (
            <span>
              DATA: {shortTime(status.timestamp)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
