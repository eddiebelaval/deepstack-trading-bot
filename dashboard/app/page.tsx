"use client";

import { useEffect, useState, useCallback } from "react";
import { centsToUSD, formatGateValue, formatStrategyName } from "@/lib/format";

// ---------------------------------------------------------------------------
// Types — match the /api/graduation response
// ---------------------------------------------------------------------------

interface DailyPnl {
  day: string;
  pnl: number;
  trades: number;
}

interface GateCheck {
  name: string;
  passed: boolean;
  current: number;
  target: number;
  format: "number" | "percent" | "cents" | "pct" | "days";
  invert?: boolean;
}

interface BacktestConfidence {
  score: number;
  strategies_tested: number;
  total_bt_trades: number;
  avg_win_rate: number;
  avg_sharpe: number;
  avg_drawdown_pct: number;
  data_source: string;
  last_run: string;
}

interface GateMetrics {
  total_trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number;
  total_pnl_cents: number;
  avg_pnl_cents: number;
  best_trade_cents: number;
  worst_trade_cents: number;
  best_trade_ticker: string;
  worst_trade_ticker: string;
  max_drawdown_pct: number;
  profitable_days: number;
  total_days: number;
  current_streak: number;
  longest_win_streak: number;
  longest_loss_streak: number;
  daily_pnl: DailyPnl[];
  strategies_active: number;
  strategies_total: number;
  regime_breakdown: { regime: string; trades: number; pnl: number }[];
}

interface GateResult {
  label: string;
  platform: string;
  thresholds: {
    min_trades: number;
    min_win_rate: number;
    max_drawdown_pct: number;
    min_profitable_days?: number;
    min_avg_pnl_cents?: number;
  };
  metrics: GateMetrics;
  gate_checks: GateCheck[];
  paper_readiness: number;
  backtest_confidence: BacktestConfidence | null;
  blended_readiness: number;
}

// ---------------------------------------------------------------------------
// Sparkline — pure SVG mini chart of daily P&L
// ---------------------------------------------------------------------------

function Sparkline({ data, width = 120, height = 28 }: { data: DailyPnl[]; width?: number; height?: number }) {
  if (data.length < 5) {
    return (
      <span className="text-[9px] text-terminal-dim/40 tabular-nums">
        {data.length}/5 days
      </span>
    );
  }

  const values = data.map((d) => d.pnl);
  const maxAbs = Math.max(...values.map(Math.abs), 1);
  const mid = height / 2;

  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = mid - (v / maxAbs) * (mid - 2);
    return `${x},${y}`;
  });

  return (
    <svg width={width} height={height} className="overflow-visible">
      <line x1={0} y1={mid} x2={width} y2={mid} stroke="rgba(0,255,65,0.1)" strokeWidth={0.5} />
      {values.map((v, i) => {
        const x = (i / (values.length - 1)) * width;
        const barH = Math.abs(v / maxAbs) * (mid - 2);
        return (
          <rect
            key={i}
            x={x - 2}
            y={v >= 0 ? mid - barH : mid}
            width={4}
            height={Math.max(barH, 1)}
            fill={v >= 0 ? "var(--terminal-green)" : "var(--terminal-red)"}
            opacity={0.6}
            rx={1}
          />
        );
      })}
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke="var(--terminal-green)"
        strokeWidth={1}
        strokeOpacity={0.4}
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// MetricBar — progress bar for gate checks
// ---------------------------------------------------------------------------

function computeRatio(current: number, target: number, invert?: boolean): number {
  if (target <= 0) return invert ? 1 : 0;
  if (invert) return Math.max(0, 1 - current / target);
  return Math.min(current / target, 1);
}

function thresholdColor(ratio: number, passed: boolean): string {
  if (passed) return "var(--terminal-green)";
  if (ratio >= 0.7) return "var(--terminal-amber)";
  return "var(--terminal-red)";
}

function MetricBar({ check }: { check: GateCheck }) {
  const ratio = computeRatio(check.current, check.target, check.invert);
  const barColor = thresholdColor(ratio, check.passed);

  return (
    <div className="mb-2">
      <div className="flex justify-between text-[10px] mb-0.5">
        <span className="flex items-center gap-1.5">
          <span
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{ background: check.passed ? "var(--terminal-green)" : "var(--terminal-red)" }}
            title={check.passed ? "PASSED" : "NOT MET"}
          />
          <span style={{ color: "var(--terminal-green-dim)" }}>{check.name}</span>
        </span>
        <span className="tabular-nums" style={{ color: barColor }}>
          {formatGateValue(check.current, check.format)} / {formatGateValue(check.target, check.format)}
        </span>
      </div>
      <div
        className="w-full rounded-sm overflow-hidden"
        style={{ height: 6, background: "rgba(0, 255, 65, 0.08)" }}
      >
        <div
          className="h-full rounded-sm transition-all duration-700"
          style={{
            width: `${Math.max(ratio * 100, 1)}%`,
            background: barColor,
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ReadinessBar — blended paper + backtest readiness
// ---------------------------------------------------------------------------

function ReadinessBar({
  paper,
  backtest,
  blended,
}: {
  paper: number;
  backtest: BacktestConfidence | null;
  blended: number;
}) {
  const hasBt = backtest !== null;
  const btPct = hasBt ? backtest.score : 0;

  return (
    <div className="mt-3 pt-2" style={{ borderTop: "1px solid rgba(0, 255, 65, 0.08)" }}>
      <div className="flex items-center justify-between text-[10px] mb-1">
        <span style={{ color: "var(--terminal-green-dim)" }}>
          {hasBt ? "BLENDED READINESS" : "PAPER READINESS"}
        </span>
        <span
          className="tabular-nums font-bold"
          style={{ color: blended >= 0.65 ? "var(--terminal-green)" : blended >= 0.4 ? "var(--terminal-amber)" : "var(--terminal-red)" }}
        >
          {(blended * 100).toFixed(0)}%
        </span>
      </div>

      <div className="w-full rounded-sm overflow-hidden flex" style={{ height: 6, background: "rgba(0, 255, 65, 0.06)" }}>
        <div
          className="h-full transition-all duration-700"
          style={{
            width: `${paper * 35}%`,
            background: "var(--terminal-cyan)",
            opacity: 0.8,
          }}
          title={`Paper: ${(paper * 100).toFixed(0)}%`}
        />
        {hasBt && (
          <div
            className="h-full transition-all duration-700"
            style={{
              width: `${(btPct / 100) * 65}%`,
              background: "var(--terminal-green)",
              opacity: 0.6,
            }}
            title={`Backtest: ${btPct.toFixed(0)}/100`}
          />
        )}
      </div>

      <div className="flex items-center justify-between text-[9px] mt-1" style={{ color: "var(--terminal-dim)", opacity: 0.5 }}>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-sm" style={{ background: "var(--terminal-cyan)", opacity: 0.8 }} />
            PAPER {(paper * 100).toFixed(0)}%
          </span>
          {hasBt && (
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-sm" style={{ background: "var(--terminal-green)", opacity: 0.6 }} />
              BACKTEST {btPct.toFixed(0)}/100
            </span>
          )}
        </div>
        {hasBt && (
          <span>35/65 WEIGHT</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BacktestBadge — compact backtest confidence indicator
// ---------------------------------------------------------------------------

function BacktestBadge({ bt }: { bt: BacktestConfidence }) {
  const color = bt.score >= 65 ? "var(--terminal-green)" : bt.score >= 40 ? "var(--terminal-amber)" : "var(--terminal-red)";

  return (
    <div
      className="mt-2 px-2 py-1.5 rounded text-[9px]"
      style={{ background: "rgba(0, 255, 65, 0.04)", border: "1px solid rgba(0, 255, 65, 0.1)" }}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="tracking-wider font-semibold" style={{ color: "var(--terminal-green-dim)" }}>
          BACKTEST
        </span>
        <span className="tabular-nums font-bold" style={{ color }}>
          {bt.score.toFixed(0)}/100
        </span>
      </div>
      <div className="grid grid-cols-3 gap-1 text-[9px]" style={{ color: "var(--terminal-dim)", opacity: 0.6 }}>
        <span className="tabular-nums">{bt.strategies_tested} strats</span>
        <span className="tabular-nums">{bt.total_bt_trades.toLocaleString()} trades</span>
        <span className="tabular-nums">S={bt.avg_sharpe.toFixed(1)}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GateCard — enriched with backtest confidence + blended readiness
// ---------------------------------------------------------------------------

function GateCard({ gate }: { gate: GateResult }) {
  const { metrics, gate_checks } = gate;

  const allPassed = gate_checks.every((c) => c.passed);

  let status: string;
  let statusBadge: string;
  if (metrics.total_trades === 0 && !gate.backtest_confidence) {
    status = "NOT STARTED";
    statusBadge = "badge-red";
  } else if (allPassed && gate.blended_readiness >= 0.65) {
    status = "GATE PASSED";
    statusBadge = "badge-green";
  } else if (metrics.total_trades === 0 && gate.backtest_confidence) {
    status = "BACKTEST ONLY";
    statusBadge = "badge-amber";
  } else {
    status = "IN PROGRESS";
    statusBadge = "badge-amber";
  }

  let streakLabel: string;
  let streakColor: string;
  if (metrics.current_streak > 0) {
    streakLabel = `${metrics.current_streak}W`;
    streakColor = "var(--terminal-green)";
  } else if (metrics.current_streak < 0) {
    streakLabel = `${Math.abs(metrics.current_streak)}L`;
    streakColor = "var(--terminal-red)";
  } else {
    streakLabel = "--";
    streakColor = "var(--terminal-dim)";
  }

  return (
    <div className="panel p-3 sm:p-4 relative">
      <div className="relative z-10">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="text-sm font-bold tracking-wider" style={{ color: "var(--terminal-green-bright)" }}>
              {gate.label}
            </h3>
            <p className="text-[10px] mt-0.5" style={{ color: "var(--terminal-green-dim)" }}>
              {gate.platform}
            </p>
          </div>
          <span className={`${statusBadge} text-[9px] font-semibold whitespace-nowrap`}>
            {status}
          </span>
        </div>

        {/* Gate Checks — progress bars */}
        {gate_checks.map((check) => (
          <MetricBar key={check.name} check={check} />
        ))}

        {/* Backtest confidence badge */}
        {gate.backtest_confidence && (
          <BacktestBadge bt={gate.backtest_confidence} />
        )}

        {/* Blended readiness bar */}
        <ReadinessBar
          paper={gate.paper_readiness}
          backtest={gate.backtest_confidence}
          blended={gate.blended_readiness}
        />

        {/* Stats grid — only show when we have trades */}
        {metrics.total_trades > 0 && (
          <>
            <div className="mt-3 pt-2 flex items-center justify-between gap-3"
              style={{ borderTop: "1px solid rgba(0, 255, 65, 0.08)" }}
            >
              <div className="flex-1 min-w-0">
                <Sparkline data={metrics.daily_pnl} />
              </div>
              <div className="text-right shrink-0">
                <div
                  className="text-sm tabular-nums font-bold"
                  style={{
                    color: metrics.total_pnl_cents >= 0 ? "var(--terminal-green)" : "var(--terminal-red)",
                    textShadow: metrics.total_pnl_cents >= 0
                      ? "0 0 4px rgba(0,255,65,0.4)"
                      : "0 0 4px rgba(255,0,0,0.4)",
                  }}
                >
                  {metrics.total_pnl_cents >= 0 ? "+" : ""}
                  {centsToUSD(metrics.total_pnl_cents)}
                </div>
                <div className="text-[9px] text-terminal-dim/40">TOTAL P&L</div>
              </div>
            </div>

            <div className="mt-2 grid grid-cols-4 gap-1 text-center">
              <div>
                <div className="text-[10px] tabular-nums font-bold" style={{ color: "var(--terminal-green)" }}>
                  {metrics.wins}W
                </div>
                <div className="text-[8px] text-terminal-dim/30">WINS</div>
              </div>
              <div>
                <div className="text-[10px] tabular-nums font-bold" style={{ color: "var(--terminal-red)" }}>
                  {metrics.losses}L
                </div>
                <div className="text-[8px] text-terminal-dim/30">LOSSES</div>
              </div>
              <div>
                <div className="text-[10px] tabular-nums font-bold" style={{ color: streakColor }}>
                  {streakLabel}
                </div>
                <div className="text-[8px] text-terminal-dim/30">STREAK</div>
              </div>
              <div>
                <div className="text-[10px] tabular-nums font-bold" style={{ color: "var(--terminal-cyan)" }}>
                  {metrics.profitable_days}/{metrics.total_days}
                </div>
                <div className="text-[8px] text-terminal-dim/30">DAYS +/-</div>
              </div>
            </div>

            <div className="mt-2 grid grid-cols-2 gap-2 text-[9px]">
              <div className="bg-terminal-bg-panel rounded px-2 py-1.5">
                <div className="text-[8px] text-terminal-dim/30 tracking-wider mb-0.5">BEST TRADE</div>
                <div className="tabular-nums font-bold" style={{ color: "var(--terminal-green)" }}>
                  +{centsToUSD(metrics.best_trade_cents)}
                </div>
                <div className="text-[9px] text-terminal-dim/30 truncate">
                  {metrics.best_trade_ticker}
                </div>
              </div>
              <div className="bg-terminal-bg-panel rounded px-2 py-1.5">
                <div className="text-[8px] text-terminal-dim/30 tracking-wider mb-0.5">WORST TRADE</div>
                <div className="tabular-nums font-bold" style={{ color: "var(--terminal-red)" }}>
                  {centsToUSD(metrics.worst_trade_cents)}
                </div>
                <div className="text-[9px] text-terminal-dim/30 truncate">
                  {metrics.worst_trade_ticker}
                </div>
              </div>
            </div>

            <div className="mt-2 flex items-center justify-between text-[9px]"
              style={{ borderTop: "1px solid rgba(0, 255, 65, 0.06)", paddingTop: 6 }}
            >
              <span className="text-terminal-dim/40">
                STRATS: <span className="text-terminal-green tabular-nums">{metrics.strategies_active}</span>
                <span className="text-terminal-dim/20">/{metrics.strategies_total}</span>
              </span>
              <span className="text-terminal-dim/40">
                LONGEST: <span className="text-terminal-green tabular-nums">{metrics.longest_win_streak}W</span>
                {" / "}
                <span className="text-terminal-red tabular-nums">{metrics.longest_loss_streak}L</span>
              </span>
            </div>

            {metrics.regime_breakdown.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {metrics.regime_breakdown.slice(0, 4).map((r) => (
                  <span
                    key={r.regime}
                    className="text-[9px] px-1.5 py-0.5 rounded border tabular-nums"
                    style={{
                      color: r.pnl >= 0 ? "var(--terminal-green-dim)" : "var(--terminal-red)",
                      borderColor: r.pnl >= 0 ? "rgba(0,255,65,0.15)" : "rgba(255,0,0,0.15)",
                      background: r.pnl >= 0 ? "rgba(0,255,65,0.03)" : "rgba(255,0,0,0.03)",
                    }}
                  >
                    {formatStrategyName(r.regime ?? "unknown")} ({r.trades})
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function GraduationPage() {
  const [gates, setGates] = useState<GateResult[]>([]);
  const [lastUpdated, setLastUpdated] = useState("");
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/graduation");
      if (res.ok) {
        const data = await res.json();
        setGates(data.gates || []);
      }
      setLastUpdated(new Date().toLocaleTimeString());
    } catch {
      // Graceful degradation
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Overall blended readiness
  const overallReadiness = gates.length > 0
    ? gates.reduce((sum, g) => sum + g.blended_readiness, 0) / gates.length
    : 0;

  const totalTrades = gates.reduce((s, g) => s + g.metrics.total_trades, 0);
  const totalPnl = gates.reduce((s, g) => s + g.metrics.total_pnl_cents, 0);
  const gatesPassed = gates.filter((g) =>
    g.gate_checks.every((c) => c.passed) && g.blended_readiness >= 0.65
  ).length;
  const hasBacktest = gates.some((g) => g.backtest_confidence !== null);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="terminal-glow text-sm animate-cursor-blink">
          LOADING GRADUATION DATA...
        </span>
      </div>
    );
  }

  return (
    <div className="p-3 sm:p-6 max-w-[1600px] mx-auto space-y-4 sm:space-y-6 pb-12">
      {/* Hero */}
      <div className="panel-hero panel p-4 sm:p-6">
        <div className="relative z-10">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h1 className="text-lg sm:text-xl font-bold tracking-wider terminal-glow-bright"
                style={{ color: "var(--terminal-green-bright)" }}>
                GRADUATION PROTOCOL
              </h1>
              <p className="text-xs mt-1" style={{ color: "var(--terminal-green-dim)" }}>
                {hasBacktest ? "Hybrid Mode — Backtest + Paper Trading" : "Paper Trading — All Asset Classes"}
              </p>
            </div>
            <div className="text-left sm:text-right">
              <div className="text-2xl sm:text-3xl font-bold tabular-nums terminal-glow-bright"
                style={{ color: "var(--terminal-green-bright)" }}>
                {(overallReadiness * 100).toFixed(0)}%
              </div>
              <div className="text-[10px] tracking-wider" style={{ color: "var(--terminal-green-dim)" }}>
                {hasBacktest ? "BLENDED READINESS" : "OVERALL READINESS"}
              </div>
            </div>
          </div>

          <div className="mt-4 w-full rounded-sm overflow-hidden"
            style={{ height: 6, background: "rgba(0, 255, 65, 0.08)" }}>
            <div className="h-full rounded-sm transition-all duration-1000"
              style={{
                width: `${overallReadiness * 100}%`,
                background: thresholdColor(overallReadiness, overallReadiness >= 0.9),
              }}
            />
          </div>

          <div className="mt-3 flex flex-wrap gap-4 text-[10px]">
            <span style={{ color: "var(--terminal-green-dim)" }}>
              GATES: <span className="text-terminal-green font-bold">{gatesPassed}/{gates.length}</span> PASSED
            </span>
            <span style={{ color: "var(--terminal-green-dim)" }}>
              TRADES: <span className="text-terminal-green font-bold tabular-nums">{totalTrades}</span>
            </span>
            <span style={{ color: "var(--terminal-green-dim)" }}>
              P&L:{" "}
              <span className="font-bold tabular-nums"
                style={{ color: totalPnl >= 0 ? "var(--terminal-green)" : "var(--terminal-red)" }}>
                {totalPnl >= 0 ? "+" : ""}{centsToUSD(totalPnl)}
              </span>
            </span>
            <span className="text-terminal-dim/30">
              SOURCE: {hasBacktest ? "Supabase + Backtest" : "Supabase (deepstack_trades)"}
            </span>
          </div>
        </div>
      </div>

      {/* Gate Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
        {gates.map((gate) => (
          <GateCard key={gate.label} gate={gate} />
        ))}
      </div>

      <div className="text-center text-[10px] pb-4"
        style={{ color: "var(--terminal-green-dim)", opacity: 0.5 }}>
        Last updated: {lastUpdated} — Refreshes every 30s
      </div>
    </div>
  );
}
