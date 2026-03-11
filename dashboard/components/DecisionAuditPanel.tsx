'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { centsToUSD, formatStrategyName, regimeColor, shortDate } from '@/lib/format';


interface RegimeSnapshot {
  regime: string;
  confidence: number;
  volatility: number | null;
  timestamp: string;
  source?: string;
}

interface FitnessRow {
  strategy_name: string;
  regime: string;
  fitness_score: number;
  trade_count: number;
  total_pnl_cents: number;
}

interface DecisionAuditCycle {
  timestamp: string;
  observed: {
    prediction_market: RegimeSnapshot | null;
    stock: RegimeSnapshot | null;
  };
  translation: {
    effective_regime: string | null;
    agreement: 'agree' | 'diverge' | 'partial' | 'unknown';
    steering_source: 'prediction_market' | 'stock' | 'both' | 'unknown';
    confidence_gap: number | null;
  };
  decisions: {
    regime: string;
    confidence: number | null;
    mode: string | null;
    enable: string[];
    disable: string[];
    reasons: string[];
  };
  context: {
    top_fitness: FitnessRow[];
  };
  outcome: {
    trade_count: number;
    net_pnl_cents: number;
    window_hours: number;
  };
}

function sourceLabel(source: 'prediction_market' | 'stock') {
  return source === 'prediction_market' ? 'PREDICTION MKTS' : 'STOCKS';
}

function agreementStyle(agreement: DecisionAuditCycle['translation']['agreement']) {
  switch (agreement) {
    case 'agree':
      return 'text-terminal-green border-terminal-green/30 bg-terminal-green/5';
    case 'diverge':
      return 'text-terminal-red border-terminal-red/30 bg-terminal-red/5';
    case 'partial':
      return 'text-terminal-amber border-terminal-amber/30 bg-terminal-amber/5';
    default:
      return 'text-terminal-dim border-terminal-dim/20 bg-terminal-bg';
  }
}

function steeringLabel(source: DecisionAuditCycle['translation']['steering_source']) {
  switch (source) {
    case 'prediction_market':
      return 'PM LEAD';
    case 'stock':
      return 'STOCK LEAD';
    case 'both':
      return 'ALIGNED';
    default:
      return 'UNCLEAR';
  }
}

function reasonSnippet(reason: string) {
  return reason.length > 72 ? `${reason.slice(0, 72)}...` : reason;
}

function SnapshotCard({
  label,
  reading,
}: {
  label: string;
  reading: RegimeSnapshot | null;
}) {
  if (!reading) {
    return (
      <div className="rounded border border-terminal-dim/10 bg-terminal-bg px-2 py-2">
        <div className="text-[8px] tracking-[0.18em] text-terminal-dim/50">{label}</div>
        <div className="mt-1 text-[9px] text-terminal-dim/40">NO READING</div>
      </div>
    );
  }

  const color = regimeColor(reading.regime);

  return (
    <div className="rounded border bg-terminal-bg px-2 py-2" style={{ borderColor: `${color}25` }}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[8px] tracking-[0.18em] text-terminal-dim/50">{label}</span>
        <span className="text-[8px] tabular-nums text-terminal-dim/40">
          {(reading.confidence * 100).toFixed(0)}% CONF
        </span>
      </div>
      <div className="mt-1 text-[10px] font-bold tracking-wide" style={{ color }}>
        {formatStrategyName(reading.regime)}
      </div>
      <div className="mt-1 flex items-center gap-3 text-[8px] tabular-nums text-terminal-dim/45">
        <span>VOL {reading.volatility != null ? `${(reading.volatility * 100).toFixed(0)}%` : '--'}</span>
        <span>{shortDate(reading.timestamp)}</span>
      </div>
    </div>
  );
}

export default function DecisionAuditPanel() {
  const [cycles, setCycles] = useState<DecisionAuditCycle[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/analytics?view=decision_audit&days=7');
      if (!res.ok) return;
      const json = await res.json();
      setCycles(json.data || []);
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const summary = useMemo(() => {
    const diverged = cycles.filter((c) => c.translation.agreement === 'diverge').length;
    const positive = cycles.filter((c) => c.outcome.net_pnl_cents > 0).length;
    const totalPnl = cycles.reduce((s, c) => s + c.outcome.net_pnl_cents, 0);
    const avgPnl = cycles.length > 0 ? Math.round(totalPnl / cycles.length) : 0;
    const positiveRate = cycles.length > 0 ? Math.round((positive / cycles.length) * 100) : 0;
    return { diverged, positive, totalPnl, avgPnl, positiveRate };
  }, [cycles]);

  // Historical pattern: how do divergences perform?
  const divergencePattern = useMemo(() => {
    const diverged = cycles.filter((c) => c.translation.agreement === 'diverge');
    if (diverged.length < 2) return null;
    const avgPnl = Math.round(diverged.reduce((s, c) => s + c.outcome.net_pnl_cents, 0) / diverged.length);
    const winRate = Math.round(diverged.filter((c) => c.outcome.net_pnl_cents > 0).length / diverged.length * 100);
    return { count: diverged.length, avgPnlCents: avgPnl, winRate };
  }, [cycles]);

  // Regime performance breakdown
  const regimePatterns = useMemo(() => {
    const byRegime = new Map<string, { count: number; totalPnl: number; wins: number }>();
    for (const cycle of cycles) {
      const regime = cycle.translation.effective_regime ?? cycle.decisions.regime ?? 'unknown';
      const entry = byRegime.get(regime) ?? { count: 0, totalPnl: 0, wins: 0 };
      entry.count++;
      entry.totalPnl += cycle.outcome.net_pnl_cents;
      if (cycle.outcome.net_pnl_cents > 0) entry.wins++;
      byRegime.set(regime, entry);
    }
    return Array.from(byRegime.entries())
      .map(([regime, d]) => ({ regime, ...d, winRate: d.count > 0 ? Math.round((d.wins / d.count) * 100) : 0 }))
      .sort((a, b) => b.totalPnl - a.totalPnl);
  }, [cycles]);

  return (
    <div className="panel-hero">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 px-3 py-2 border-b border-terminal-green/20">
        <div>
          <div className="text-[10px] font-bold tracking-[0.15em] terminal-glow">
            DECISION AUDIT
          </div>
          <div className="text-[9px] text-terminal-dim/45 tracking-[0.12em]">
            SENSE &rarr; TRANSLATE &rarr; DECIDE &rarr; OUTCOME (7D)
          </div>
        </div>
        <div className="flex items-center gap-3 text-[9px] text-terminal-dim">
          <span>{cycles.length} CYCLES</span>
          <span>{summary.diverged} DIVERGED</span>
          <span>{summary.positive} POSITIVE</span>
        </div>
      </div>

      {/* Summary Stats Bar */}
      {cycles.length > 0 && (
        <div className="px-3 py-2 border-b border-terminal-green/10">
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
            {[
              { label: 'NET PNL', value: centsToUSD(summary.totalPnl), color: summary.totalPnl >= 0 ? 'text-terminal-green' : 'text-terminal-red' },
              { label: 'AVG / CYCLE', value: centsToUSD(summary.avgPnl), color: summary.avgPnl >= 0 ? 'text-terminal-green' : 'text-terminal-red' },
              { label: 'WIN RATE', value: `${summary.positiveRate}%`, color: summary.positiveRate >= 50 ? 'text-terminal-green' : 'text-terminal-amber' },
              { label: 'DIVERGENCES', value: `${summary.diverged}`, color: summary.diverged > 0 ? 'text-terminal-amber' : 'text-terminal-dim' },
              { label: 'TOTAL CYCLES', value: `${cycles.length}`, color: 'text-terminal-dim' },
            ].map((s) => (
              <div key={s.label} className="px-2 py-1.5 rounded border border-terminal-green/8 bg-terminal-bg-panel/40">
                <div className="text-[8px] text-terminal-dim/50 tracking-[0.15em]">{s.label}</div>
                <div className={`text-sm font-bold tabular-nums ${s.color}`}>{s.value}</div>
              </div>
            ))}
          </div>

          {/* Divergence pattern callout */}
          {divergencePattern && (
            <div className="mt-2 px-2 py-1.5 rounded border border-terminal-amber/15 bg-terminal-amber/[0.03] text-[9px]">
              <span className="text-terminal-amber font-bold">PATTERN:</span>
              <span className="text-terminal-dim/70 ml-1.5">
                Last {divergencePattern.count} divergences: avg {centsToUSD(divergencePattern.avgPnlCents)}/cycle, {divergencePattern.winRate}% win rate
              </span>
            </div>
          )}

          {/* Regime performance grid */}
          {regimePatterns.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {regimePatterns.map((rp) => (
                <div
                  key={rp.regime}
                  className="px-2 py-1 rounded border text-[8px] tabular-nums"
                  style={{
                    borderColor: `${regimeColor(rp.regime)}20`,
                    color: regimeColor(rp.regime),
                  }}
                >
                  <span className="font-bold">{formatStrategyName(rp.regime)}</span>
                  <span className="text-terminal-dim/50 ml-1">{rp.count}x</span>
                  <span className={`ml-1 ${rp.totalPnl >= 0 ? 'text-terminal-green' : 'text-terminal-red'}`}>
                    {centsToUSD(rp.totalPnl)}
                  </span>
                  <span className="text-terminal-dim/40 ml-1">{rp.winRate}%W</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {loading ? (
        <div className="p-4 text-[10px] text-terminal-dim text-center">
          LOADING DECISION AUDIT<span className="animate-cursor-blink">_</span>
        </div>
      ) : cycles.length === 0 ? (
        <div className="p-4 text-[10px] text-terminal-dim text-center">
          NO GOVERNANCE CYCLES YET
        </div>
      ) : (
        <div className="p-3 space-y-3">
          {cycles.map((cycle) => {
            const regime = cycle.translation.effective_regime ?? cycle.decisions.regime;
            const color = regimeColor(regime || 'low_vol_calm');
            const outcomePositive = cycle.outcome.net_pnl_cents >= 0;
            const fitness = cycle.context.top_fitness.slice(0, 3);

            return (
              <div
                key={cycle.timestamp}
                className="rounded-lg border bg-terminal-bg-panel p-3 space-y-3"
                style={{ borderColor: `${color}20` }}
              >
                <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[9px] text-terminal-dim/45 tracking-[0.16em]">
                      {shortDate(cycle.timestamp)}
                    </span>
                    <span
                      className="text-[10px] font-bold tracking-[0.14em]"
                      style={{ color }}
                    >
                      {formatStrategyName(regime || 'unknown')}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded border text-[8px] tracking-[0.16em] ${agreementStyle(cycle.translation.agreement)}`}
                    >
                      {cycle.translation.agreement.toUpperCase()}
                    </span>
                    <span className="text-[8px] text-terminal-cyan border border-terminal-cyan/20 bg-terminal-cyan/5 rounded px-2 py-0.5 tracking-[0.16em]">
                      {steeringLabel(cycle.translation.steering_source)}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 text-[9px] tabular-nums">
                    <span className={outcomePositive ? 'text-terminal-green' : 'text-terminal-red'}>
                      {outcomePositive ? '+' : ''}
                      {centsToUSD(cycle.outcome.net_pnl_cents)}
                    </span>
                    <span className="text-terminal-dim/50">
                      {cycle.outcome.trade_count} TRADES / {cycle.outcome.window_hours}H
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_0.9fr_1fr_0.95fr] gap-3">
                  <div className="space-y-2">
                    <div className="text-[8px] tracking-[0.18em] text-terminal-dim/45">SENSE</div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      <SnapshotCard
                        label={sourceLabel('prediction_market')}
                        reading={cycle.observed.prediction_market}
                      />
                      <SnapshotCard
                        label={sourceLabel('stock')}
                        reading={cycle.observed.stock}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[8px] tracking-[0.18em] text-terminal-dim/45">TRANSLATE</div>
                    <div className="rounded border border-terminal-green/10 bg-terminal-bg px-2 py-2 space-y-1.5 text-[9px]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-terminal-dim/45">EFFECTIVE</span>
                        <span style={{ color }} className="font-bold">
                          {formatStrategyName(regime || 'unknown')}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-terminal-dim/45">CONF GAP</span>
                        <span className="tabular-nums text-terminal-dim">
                          {cycle.translation.confidence_gap != null
                            ? `${(cycle.translation.confidence_gap * 100).toFixed(0)} pts`
                            : '--'}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-terminal-dim/45">MODE</span>
                        <span className="text-terminal-cyan">
                          {(cycle.decisions.mode || 'unknown').toUpperCase()}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[8px] tracking-[0.18em] text-terminal-dim/45">DECIDE</div>
                    <div className="rounded border border-terminal-green/10 bg-terminal-bg px-2 py-2 space-y-2 text-[9px]">
                      <div>
                        <div className="text-terminal-green/80 tracking-[0.14em]">ENABLE</div>
                        <div className="mt-1 text-terminal-dim">
                          {cycle.decisions.enable.length > 0
                            ? cycle.decisions.enable.slice(0, 4).map(formatStrategyName).join(' / ')
                            : 'NONE'}
                        </div>
                      </div>
                      <div>
                        <div className="text-terminal-red/80 tracking-[0.14em]">DISABLE</div>
                        <div className="mt-1 text-terminal-dim">
                          {cycle.decisions.disable.length > 0
                            ? cycle.decisions.disable.slice(0, 4).map(formatStrategyName).join(' / ')
                            : 'NONE'}
                        </div>
                      </div>
                      <div>
                        <div className="text-terminal-dim/45 tracking-[0.14em]">WHY</div>
                        <div className="mt-1 text-terminal-dim/70">
                          {cycle.decisions.reasons.length > 0
                            ? reasonSnippet(cycle.decisions.reasons[0])
                            : 'No reason recorded'}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[8px] tracking-[0.18em] text-terminal-dim/45">OUTCOME</div>
                    <div className="rounded border border-terminal-green/10 bg-terminal-bg px-2 py-2 space-y-2 text-[9px]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-terminal-dim/45">REALIZED</span>
                        <span className={outcomePositive ? 'text-terminal-green' : 'text-terminal-red'}>
                          {outcomePositive ? '+' : ''}
                          {centsToUSD(cycle.outcome.net_pnl_cents)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-terminal-dim/45">TRADES</span>
                        <span className="tabular-nums text-terminal-dim">{cycle.outcome.trade_count}</span>
                      </div>
                      <div>
                        <div className="text-terminal-dim/45 tracking-[0.14em]">TOP FITNESS</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {fitness.length > 0 ? (
                            fitness.map((row) => (
                              <span
                                key={`${cycle.timestamp}-${row.strategy_name}`}
                                className="text-[8px] rounded border border-terminal-cyan/15 bg-terminal-cyan/5 px-1.5 py-0.5 text-terminal-cyan"
                              >
                                {formatStrategyName(row.strategy_name)} {(row.fitness_score * 100).toFixed(0)}
                              </span>
                            ))
                          ) : (
                            <span className="text-terminal-dim/45">No fitness rows</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
