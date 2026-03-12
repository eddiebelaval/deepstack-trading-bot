'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { centsToUSD, formatStrategyName, regimeColor, shortDate } from '@/lib/format';
import type { DecisionAuditCycle } from '@/lib/weather-types';

function agreementBadge(agreement: DecisionAuditCycle['translation']['agreement']) {
  switch (agreement) {
    case 'agree':
      return 'text-terminal-green bg-terminal-green/10';
    case 'diverge':
      return 'text-terminal-red bg-terminal-red/10';
    case 'partial':
      return 'text-terminal-amber bg-terminal-amber/10';
    default:
      return 'text-terminal-dim bg-terminal-dim/10';
  }
}

function steeringLabel(source: DecisionAuditCycle['translation']['steering_source']) {
  switch (source) {
    case 'prediction_market': return 'PM';
    case 'stock': return 'STK';
    case 'both': return 'BOTH';
    default: return '--';
  }
}

export default function DecisionAuditPanel() {
  const [cycles, setCycles] = useState<DecisionAuditCycle[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const prevCyclesRef = useRef('');

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/analytics?view=decision_audit&days=7');
      if (!res.ok) return;
      const json = await res.json();
      const serialized = JSON.stringify(json.data || []);
      if (serialized !== prevCyclesRef.current) {
        prevCyclesRef.current = serialized;
        setCycles(json.data || []);
      }
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

  const { summary, divergencePattern, regimePatterns } = useMemo(() => {
    let divergedCount = 0;
    let positiveCount = 0;
    let totalPnl = 0;
    let divPnl = 0;
    let divWins = 0;
    const byRegime = new Map<string, { count: number; totalPnl: number; wins: number }>();

    for (const c of cycles) {
      const pnl = c.outcome.net_pnl_cents;
      totalPnl += pnl;
      if (pnl > 0) positiveCount++;
      if (c.translation.agreement === 'diverge') {
        divergedCount++;
        divPnl += pnl;
        if (pnl > 0) divWins++;
      }
      const regime = c.translation.effective_regime ?? c.decisions.regime ?? 'unknown';
      const entry = byRegime.get(regime) ?? { count: 0, totalPnl: 0, wins: 0 };
      entry.count++;
      entry.totalPnl += pnl;
      if (pnl > 0) entry.wins++;
      byRegime.set(regime, entry);
    }

    return {
      summary: {
        diverged: divergedCount,
        positive: positiveCount,
        totalPnl,
        avgPnl: cycles.length > 0 ? Math.round(totalPnl / cycles.length) : 0,
        positiveRate: cycles.length > 0 ? Math.round((positiveCount / cycles.length) * 100) : 0,
      },
      divergencePattern: divergedCount >= 2
        ? { count: divergedCount, avgPnlCents: Math.round(divPnl / divergedCount), winRate: Math.round((divWins / divergedCount) * 100) }
        : null,
      regimePatterns: Array.from(byRegime.entries())
        .map(([regime, d]) => ({ regime, ...d, winRate: d.count > 0 ? Math.round((d.wins / d.count) * 100) : 0 }))
        .sort((a, b) => b.totalPnl - a.totalPnl),
    };
  }, [cycles]);

  const selected = selectedIdx != null ? cycles[selectedIdx] : null;

  return (
    <div className="panel-hero">
      {/* Header */}
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

      {/* Summary Stats */}
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
                <div className="text-[9px] text-terminal-dim/50 tracking-[0.15em]">{s.label}</div>
                <div className={`text-sm font-bold tabular-nums ${s.color}`}>{s.value}</div>
              </div>
            ))}
          </div>

          {divergencePattern && (
            <div className="mt-2 px-2 py-1.5 rounded border border-terminal-amber/15 bg-terminal-amber/[0.03] text-[9px]">
              <span className="text-terminal-amber font-bold">PATTERN:</span>
              <span className="text-terminal-dim/70 ml-1.5">
                Last {divergencePattern.count} divergences: avg {centsToUSD(divergencePattern.avgPnlCents)}/cycle, {divergencePattern.winRate}% win rate
              </span>
            </div>
          )}

          {regimePatterns.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {regimePatterns.map((rp) => (
                <div
                  key={rp.regime}
                  className="px-2 py-1 rounded border text-[9px] tabular-nums"
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

      {/* Cycle Log — compact scrollable rows */}
      {loading ? (
        <div className="p-4 text-[10px] text-terminal-dim text-center">
          LOADING DECISION AUDIT<span className="animate-cursor-blink">_</span>
        </div>
      ) : cycles.length === 0 ? (
        <div className="p-4 text-[10px] text-terminal-dim text-center">
          NO GOVERNANCE CYCLES YET
        </div>
      ) : (
        <div className="max-h-[280px] overflow-y-auto">
          {cycles.map((cycle, i) => {
            const regime = cycle.translation.effective_regime ?? cycle.decisions.regime;
            const color = regimeColor(regime || 'low_vol_calm');
            const pnl = cycle.outcome.net_pnl_cents;
            const positive = pnl >= 0;
            const isSelected = selectedIdx === i;

            return (
              <button
                key={cycle.timestamp}
                type="button"
                onClick={() => setSelectedIdx(isSelected ? null : i)}
                className={`w-full text-left flex items-center gap-2 px-3 py-1.5 text-[10px] border-b border-terminal-green/5 transition-colors ${
                  isSelected
                    ? 'bg-terminal-green/8'
                    : 'hover:bg-terminal-bg-elevated/50'
                }`}
              >
                {/* Timestamp */}
                <span className="shrink-0 w-[90px] tabular-nums text-terminal-dim/50 text-[9px]">
                  {shortDate(cycle.timestamp)}
                </span>
                {/* Regime dot + name */}
                <span className="shrink-0 flex items-center gap-1.5 w-[100px]">
                  <span
                    className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ backgroundColor: color }}
                  />
                  <span className="truncate text-[9px] font-bold" style={{ color }}>
                    {formatStrategyName(regime || 'unknown')}
                  </span>
                </span>
                {/* Agreement badge */}
                <span className={`shrink-0 px-1.5 py-0 rounded text-[8px] tracking-wider font-bold ${agreementBadge(cycle.translation.agreement)}`}>
                  {cycle.translation.agreement === 'agree' ? 'AGR' : cycle.translation.agreement === 'diverge' ? 'DIV' : 'PRT'}
                </span>
                {/* Steering */}
                <span className="shrink-0 w-8 text-[9px] text-terminal-cyan-dim text-center">
                  {steeringLabel(cycle.translation.steering_source)}
                </span>
                {/* Trades */}
                <span className="shrink-0 w-6 text-right tabular-nums text-terminal-dim text-[9px]">
                  {cycle.outcome.trade_count}t
                </span>
                {/* P&L — right aligned, pushed to end */}
                <span className={`ml-auto shrink-0 tabular-nums font-bold text-right w-14 ${positive ? 'text-terminal-green' : 'text-terminal-red'}`}>
                  {positive ? '+' : ''}{centsToUSD(pnl)}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Expanded detail for selected cycle */}
      {selected && (
        <div className="px-3 py-2 border-t border-terminal-green/15 bg-terminal-bg-panel/30 space-y-2 animate-fade-in">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[9px]">
            {/* Sense */}
            <div className="space-y-1">
              <div className="tracking-[0.16em] text-terminal-dim/50">SENSE</div>
              {(['prediction_market', 'stock'] as const).map((src) => {
                const reading = selected.observed[src];
                if (!reading) return (
                  <div key={src} className="text-terminal-dim/30">
                    {src === 'prediction_market' ? 'PM' : 'STK'}: no data
                  </div>
                );
                return (
                  <div key={src} className="flex items-center gap-1.5">
                    <span className="text-terminal-dim/50">{src === 'prediction_market' ? 'PM' : 'STK'}:</span>
                    <span style={{ color: regimeColor(reading.regime) }} className="font-bold">
                      {formatStrategyName(reading.regime)}
                    </span>
                    <span className="text-terminal-dim/40 tabular-nums">
                      {(reading.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                );
              })}
            </div>
            {/* Translate */}
            <div className="space-y-1">
              <div className="tracking-[0.16em] text-terminal-dim/50">TRANSLATE</div>
              <div className="text-terminal-dim">
                Conf gap: {selected.translation.confidence_gap != null
                  ? `${(selected.translation.confidence_gap * 100).toFixed(0)} pts`
                  : '--'}
              </div>
              <div className="text-terminal-cyan">
                Mode: {(selected.decisions.mode || 'unknown').toUpperCase()}
              </div>
            </div>
            {/* Decide */}
            <div className="space-y-1">
              <div className="tracking-[0.16em] text-terminal-dim/50">DECIDE</div>
              <div>
                <span className="text-terminal-green/80">ON: </span>
                <span className="text-terminal-dim">
                  {selected.decisions.enable.length > 0
                    ? selected.decisions.enable.slice(0, 3).map(formatStrategyName).join(', ')
                    : 'none'}
                </span>
              </div>
              <div>
                <span className="text-terminal-red/80">OFF: </span>
                <span className="text-terminal-dim">
                  {selected.decisions.disable.length > 0
                    ? selected.decisions.disable.slice(0, 3).map(formatStrategyName).join(', ')
                    : 'none'}
                </span>
              </div>
            </div>
            {/* Outcome */}
            <div className="space-y-1">
              <div className="tracking-[0.16em] text-terminal-dim/50">OUTCOME</div>
              <div className={selected.outcome.net_pnl_cents >= 0 ? 'text-terminal-green' : 'text-terminal-red'}>
                {selected.outcome.net_pnl_cents >= 0 ? '+' : ''}{centsToUSD(selected.outcome.net_pnl_cents)}
                <span className="text-terminal-dim/50 ml-1">
                  / {selected.outcome.window_hours}h
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {selected.context.top_fitness.slice(0, 3).map((row) => (
                  <span
                    key={row.strategy_name}
                    className="rounded bg-terminal-cyan/5 border border-terminal-cyan/15 px-1 py-0 text-terminal-cyan text-[8px]"
                  >
                    {formatStrategyName(row.strategy_name)} {(row.fitness_score * 100).toFixed(0)}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {/* Reason */}
          {selected.decisions.reasons.length > 0 && (
            <div className="text-[9px] text-terminal-dim/60 border-t border-terminal-green/8 pt-1.5">
              {selected.decisions.reasons[0]}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
