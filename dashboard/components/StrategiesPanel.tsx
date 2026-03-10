'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import type { StrategyStatus } from '@/lib/types';
import { healthDot, formatStrategyName } from '@/lib/format';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RegimeContext {
  regime: string;
  confidence: number;
  timestamp: string;
  source: string;
}

interface FitnessEntry {
  strategy_name: string;
  regime: string;
  fitness_score: number;
  trade_count: number;
  total_pnl_cents: number;
}

interface Props {
  strategies: StrategyStatus[];
  onToggle: (name: string, enabled: boolean) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const IBKR_STRATEGIES = new Set([
  'stock_momentum',
  'crisis_alpha',
  'futures_trend',
  'options_income',
  'options_directional',
]);

const ENABLE_THRESHOLD = 0.5;

function regimeBanner(regime: string): { label: string; color: string; bg: string } {
  switch (regime) {
    case 'high_vol_choppy':
      return { label: 'HIGH VOL CHOPPY', color: 'text-terminal-red', bg: 'border-terminal-red/30 bg-terminal-red/5' };
    case 'low_vol_calm':
      return { label: 'LOW VOL CALM', color: 'text-terminal-green', bg: 'border-terminal-green/30 bg-terminal-green/5' };
    case 'trending_up':
      return { label: 'TRENDING UP', color: 'text-terminal-cyan', bg: 'border-terminal-cyan/30 bg-terminal-cyan/5' };
    case 'trending_down':
      return { label: 'TRENDING DOWN', color: 'text-terminal-amber', bg: 'border-terminal-amber/30 bg-terminal-amber/5' };
    case 'mean_reverting':
      return { label: 'MEAN REVERTING', color: 'text-purple-400', bg: 'border-purple-400/30 bg-purple-400/5' };
    default:
      return { label: formatStrategyName(regime), color: 'text-terminal-dim', bg: 'border-terminal-dim/30 bg-terminal-dim/5' };
  }
}

function confidenceBarColor(confidence: number): string {
  if (confidence > 0.7) return 'var(--terminal-green)';
  if (confidence > 0.4) return 'var(--terminal-amber)';
  return 'var(--terminal-red)';
}

function fitnessBar(score: number): string {
  if (score >= 0.7) return 'bg-terminal-green';
  if (score >= ENABLE_THRESHOLD) return 'bg-terminal-green/60';
  if (score >= 0.3) return 'bg-terminal-amber/60';
  return 'bg-terminal-red/40';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function StrategiesPanel({ strategies, onToggle }: Props) {
  const [regime, setRegime] = useState<RegimeContext | null>(null);
  const [fitness, setFitness] = useState<FitnessEntry[]>([]);
  const [benchedExpanded, setBenchedExpanded] = useState(false);
  const [ibkrExpanded, setIbkrExpanded] = useState(false);

  // Fetch current regime (via market_state — lighter than regime_timeline) + fitness
  const fetchRegimeData = useCallback(async () => {
    try {
      const [marketRes, fitnessRes] = await Promise.all([
        fetch('/api/analytics?view=market_state'),
        fetch('/api/analytics?view=fitness_heatmap'),
      ]);
      if (marketRes.ok) {
        const d = await marketRes.json();
        const readings = d.data || [];
        // Use prediction_market source as primary regime, fall back to first available
        const primary = readings.find((r: { source: string }) => r.source === 'prediction_market') ?? readings[0];
        if (primary) {
          setRegime({
            regime: primary.regime,
            confidence: primary.confidence,
            timestamp: primary.timestamp,
            source: primary.source || 'unknown',
          });
        }
      }
      if (fitnessRes.ok) {
        const d = await fitnessRes.json();
        setFitness(d.data || []);
      }
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    fetchRegimeData();
    const interval = setInterval(fetchRegimeData, 30_000);
    return () => clearInterval(interval);
  }, [fetchRegimeData]);

  // Split strategies into tiers based on current regime fitness
  const { inPlay, benched, ibkr } = useMemo(() => {
    const fitnessMap = new Map<string, number>();
    if (regime) {
      for (const f of fitness) {
        if (f.regime === regime.regime) {
          fitnessMap.set(f.strategy_name, f.fitness_score);
        }
      }
    }

    const inPlay: (StrategyStatus & { fitness: number })[] = [];
    const benched: (StrategyStatus & { fitness: number })[] = [];
    const ibkr: StrategyStatus[] = [];

    for (const s of strategies) {
      if (IBKR_STRATEGIES.has(s.name)) {
        ibkr.push(s);
        continue;
      }

      const fit = fitnessMap.get(s.name) ?? 0;
      const strat = { ...s, fitness: fit };

      // "In play" = fitness above threshold OR currently enabled/active
      if (fit >= ENABLE_THRESHOLD || s.enabled) {
        inPlay.push(strat);
      } else {
        benched.push(strat);
      }
    }

    // Sort in-play by fitness descending
    inPlay.sort((a, b) => b.fitness - a.fitness);
    benched.sort((a, b) => b.fitness - a.fitness);

    return { inPlay, benched, ibkr };
  }, [strategies, regime, fitness]);

  const regimeStyle = regime ? regimeBanner(regime.regime) : null;
  const confidencePct = regime ? (regime.confidence * 100).toFixed(0) : '0';

  return (
    <div className="panel">
      {/* Regime Banner */}
      {regime ? (
        <div className={`flex items-center justify-between px-3 py-2 border-b ${regimeStyle?.bg}`}>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold tracking-[0.15em] text-terminal-dim">
              REGIME
            </span>
            <span className={`text-[11px] font-bold tracking-wider ${regimeStyle?.color}`}>
              {regimeStyle?.label}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] text-terminal-dim tracking-wider">CONF</span>
              <span className={`text-[10px] font-bold tabular-nums ${regimeStyle?.color}`}>
                {confidencePct}%
              </span>
            </div>
            {/* Confidence bar */}
            <div className="w-16 h-1.5 rounded-full bg-terminal-bg overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${Math.min(Number(confidencePct), 100)}%`,
                  background: confidenceBarColor(regime.confidence),
                }}
              />
            </div>
            <span className="text-[8px] text-terminal-dim/50 tracking-wider">
              {regime.source.toUpperCase()}
            </span>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between px-3 py-2 border-b border-terminal-green/20">
          <span className="text-[10px] font-bold tracking-[0.15em] terminal-glow">
            STRATEGIES
          </span>
          <span className="text-[10px] text-terminal-dim">
            {strategies.filter((s) => s.enabled).length} / {strategies.length} ACTIVE
          </span>
        </div>
      )}

      {/* In Play Section */}
      <div className="px-3 pt-2 pb-1">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[9px] font-bold tracking-[0.2em] text-terminal-green">
            IN PLAY
          </span>
          <span className="text-[9px] text-terminal-dim tabular-nums">
            {inPlay.length}
          </span>
        </div>
        {inPlay.length === 0 ? (
          <div className="text-[10px] text-terminal-dim py-2">
            NO STRATEGIES FIT CURRENT REGIME
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {inPlay.map((s) => (
              <StrategyCard key={s.name} strategy={s} fitness={s.fitness} onToggle={onToggle} />
            ))}
          </div>
        )}
      </div>

      {/* Benched Section */}
      {benched.length > 0 && (
        <div className="border-t border-terminal-green/10 px-3 py-1.5">
          <button
            onClick={() => setBenchedExpanded(!benchedExpanded)}
            className="flex items-center gap-2 w-full text-left group"
          >
            <span
              className="text-[9px] text-terminal-dim transition-transform"
              style={{ transform: benchedExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
            >
              &gt;
            </span>
            <span className="text-[9px] font-bold tracking-[0.2em] text-terminal-dim">
              BENCHED
            </span>
            <span className="text-[9px] text-terminal-dim/50 tabular-nums">
              {benched.length}
            </span>
            {!benchedExpanded && (
              <span className="text-[8px] text-terminal-dim/30 truncate">
                {benched.slice(0, 4).map((s) => formatStrategyName(s.name).slice(0, 8)).join(' / ')}
                {benched.length > 4 ? ' ...' : ''}
              </span>
            )}
          </button>
          {benchedExpanded && (
            <div className="mt-1.5 space-y-1">
              {benched.map((s) => (
                <div
                  key={s.name}
                  className="flex items-center justify-between py-1 text-[9px]"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${healthDot(s.health_status)}`}
                    />
                    <span className="text-terminal-dim">
                      {formatStrategyName(s.name)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-terminal-dim/50 tabular-nums">
                      fit: {(s.fitness * 100).toFixed(0)}%
                    </span>
                    <button
                      onClick={() => onToggle(s.name, !s.enabled)}
                      className={`px-1.5 py-0.5 text-[8px] rounded border transition-all ${
                        s.enabled
                          ? 'border-terminal-green/30 text-terminal-green'
                          : 'border-terminal-dim/20 text-terminal-dim/40'
                      }`}
                    >
                      {s.enabled ? 'ON' : 'OFF'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* IBKR Section */}
      {ibkr.length > 0 && (
        <div className="border-t border-terminal-green/10 px-3 py-1.5">
          <button
            onClick={() => setIbkrExpanded(!ibkrExpanded)}
            className="flex items-center gap-2 w-full text-left"
          >
            <span
              className="text-[9px] text-terminal-dim transition-transform"
              style={{ transform: ibkrExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
            >
              &gt;
            </span>
            <span className="text-[9px] font-bold tracking-[0.2em] text-terminal-cyan/70">
              IBKR
            </span>
            <span className="text-[9px] text-terminal-dim/50 tabular-nums">
              {ibkr.length}
            </span>
            {!ibkrExpanded && (
              <span className="text-[8px] text-terminal-dim/30 truncate">
                {ibkr.filter((s) => s.enabled).length} active
              </span>
            )}
          </button>
          {ibkrExpanded && (
            <div className="mt-1.5 space-y-1">
              {ibkr.map((s) => (
                <div
                  key={s.name}
                  className="flex items-center justify-between py-1 text-[9px]"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${healthDot(s.health_status)}`}
                    />
                    <span className={s.enabled ? 'text-terminal-cyan' : 'text-terminal-dim'}>
                      {formatStrategyName(s.name)}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    {s.blended_win_rate != null && (
                      <span className="text-terminal-dim/50 tabular-nums">
                        WR {(s.blended_win_rate * 100).toFixed(0)}%
                      </span>
                    )}
                    <button
                      onClick={() => onToggle(s.name, !s.enabled)}
                      className={`px-1.5 py-0.5 text-[8px] rounded border transition-all ${
                        s.enabled
                          ? 'border-terminal-cyan/30 text-terminal-cyan'
                          : 'border-terminal-dim/20 text-terminal-dim/40'
                      }`}
                    >
                      {s.enabled ? 'ON' : 'OFF'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Strategy Card (hero tier — only for "in play" strategies)
// ---------------------------------------------------------------------------

function StrategyCard({
  strategy: s,
  fitness,
  onToggle,
}: {
  strategy: StrategyStatus;
  fitness: number;
  onToggle: (name: string, enabled: boolean) => void;
}) {
  const isActive = s.enabled && (s.status === 'active' || s.status === 'scanning');

  return (
    <div className="p-2.5 bg-terminal-bg-panel rounded border border-terminal-green/10 hover:border-terminal-green/25 transition-all">
      {/* Row 1: Name + toggle */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span
            className={`inline-block w-2 h-2 rounded-full shrink-0 ${healthDot(s.health_status)} ${
              isActive ? 'animate-pulse' : ''
            }`}
            title={s.health_status ?? 'unknown'}
          />
          <span className="text-[10px] text-terminal-green truncate font-semibold tracking-wide">
            {formatStrategyName(s.name)}
          </span>
          {s.auto_disabled && (
            <span className="text-[8px] text-terminal-red/80 border border-terminal-red/20 rounded px-1">
              AUTO-OFF
            </span>
          )}
        </div>
        <button
          onClick={() => onToggle(s.name, !s.enabled)}
          role="switch"
          aria-checked={s.enabled}
          className={`relative w-8 h-4 rounded-full transition-colors p-1 min-w-[44px] min-h-[44px] flex items-center ${
            s.enabled
              ? 'bg-terminal-green/30 border border-terminal-green/50'
              : 'bg-terminal-bg border border-terminal-green-dim/30'
          }`}
          title={s.enabled ? 'Disable strategy' : 'Enable strategy'}
        >
          <span
            className={`block w-3 h-3 rounded-full transition-all ${
              s.enabled
                ? 'ml-auto bg-terminal-green shadow-[0_0_4px_rgba(0,255,65,0.6)]'
                : 'mr-auto bg-terminal-green-dim/50'
            }`}
          />
        </button>
      </div>

      {/* Row 2: Stats */}
      <div className="flex items-center gap-3 text-[9px] text-terminal-dim mb-1.5">
        <span className="tabular-nums">
          WR{' '}
          <span className="text-terminal-green">
            {s.blended_win_rate != null ? `${(s.blended_win_rate * 100).toFixed(0)}%` : '--'}
          </span>
        </span>
        <span className="tabular-nums">
          EV{' '}
          <span className="text-terminal-green">
            {s.blended_ev_cents != null ? `${s.blended_ev_cents.toFixed(0)}c` : '--'}
          </span>
        </span>
        <span className="tabular-nums">
          POS{' '}
          <span className="text-terminal-cyan">{s.active_positions}</span>
        </span>
      </div>

      {/* Row 3: Fitness bar */}
      <div className="flex items-center gap-2">
        <span className="text-[8px] text-terminal-dim/50 w-6">FIT</span>
        <div className="flex-1 h-1 rounded-full bg-terminal-bg overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${fitnessBar(fitness)}`}
            style={{ width: `${Math.min(fitness * 100, 100)}%` }}
          />
        </div>
        <span className="text-[8px] text-terminal-dim tabular-nums w-6 text-right">
          {(fitness * 100).toFixed(0)}
        </span>
      </div>
    </div>
  );
}

