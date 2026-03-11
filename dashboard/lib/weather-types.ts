// ---------------------------------------------------------------------------
// Shared types and constants for the weather/regime system
// ---------------------------------------------------------------------------

export interface MarketReading {
  source: string;
  regime: string;
  confidence: number;
  volatility: number;
  trend_strength: number;
  mean_reversion_score: number;
  volume_ratio: number;
  num_markets_sampled: number;
  timestamp: string;
}

export interface RegimePoint {
  id: number;
  regime: string;
  confidence: number;
  timestamp: string;
  volatility: number;
  trend_strength: number;
  source: string;
}

// ---------------------------------------------------------------------------
// Beaufort Scale — composite market intensity
// ---------------------------------------------------------------------------

export const BEAUFORT_SCALE: { max: number; label: string; description: string; seaState: string }[] = [
  { max: 0.05, label: '0', description: 'CALM', seaState: 'Glassy' },
  { max: 0.1,  label: '1', description: 'LIGHT AIR', seaState: 'Rippled' },
  { max: 0.15, label: '2', description: 'LIGHT BREEZE', seaState: 'Small wavelets' },
  { max: 0.25, label: '3', description: 'GENTLE BREEZE', seaState: 'Large wavelets' },
  { max: 0.35, label: '4', description: 'MODERATE', seaState: 'Small waves' },
  { max: 0.45, label: '5', description: 'FRESH BREEZE', seaState: 'Moderate waves' },
  { max: 0.55, label: '6', description: 'STRONG BREEZE', seaState: 'Large waves' },
  { max: 0.65, label: '7', description: 'HIGH WIND', seaState: 'Sea heaps up' },
  { max: 0.75, label: '8', description: 'GALE', seaState: 'Mod. high waves' },
  { max: 0.85, label: '9', description: 'STRONG GALE', seaState: 'High waves' },
  { max: 0.92, label: '10', description: 'STORM', seaState: 'Very high waves' },
  { max: 0.97, label: '11', description: 'VIOLENT STORM', seaState: 'Exceptionally high' },
  { max: 1.01, label: '12', description: 'HURRICANE', seaState: 'Catastrophic' },
];

// ---------------------------------------------------------------------------
// Advisory levels
// ---------------------------------------------------------------------------

export type AdvisoryLevel = 'ALL_CLEAR' | 'SMALL_CRAFT' | 'GALE_WARNING' | 'STORM_WARNING';

export interface Advisory {
  level: AdvisoryLevel;
  label: string;
  color: string;
  glow: string;
  borderColor: string;
  bgColor: string;
}

export const ADVISORIES: Record<AdvisoryLevel, Advisory> = {
  ALL_CLEAR: {
    level: 'ALL_CLEAR', label: 'ALL CLEAR',
    color: '#00FF41', glow: '0 0 8px rgba(0,255,65,0.4)',
    borderColor: 'rgba(0,255,65,0.3)', bgColor: 'rgba(0,255,65,0.05)',
  },
  SMALL_CRAFT: {
    level: 'SMALL_CRAFT', label: 'SMALL CRAFT ADVISORY',
    color: '#FFBF00', glow: '0 0 8px rgba(255,191,0,0.4)',
    borderColor: 'rgba(255,191,0,0.3)', bgColor: 'rgba(255,191,0,0.05)',
  },
  GALE_WARNING: {
    level: 'GALE_WARNING', label: 'GALE WARNING',
    color: '#FF0000', glow: '0 0 8px rgba(255,0,0,0.4)',
    borderColor: 'rgba(255,0,0,0.3)', bgColor: 'rgba(255,0,0,0.05)',
  },
  STORM_WARNING: {
    level: 'STORM_WARNING', label: 'STORM WARNING',
    color: '#FF3333', glow: '0 0 12px rgba(255,0,0,0.6)',
    borderColor: 'rgba(255,0,0,0.5)', bgColor: 'rgba(255,0,0,0.1)',
  },
};

// ---------------------------------------------------------------------------
// Front types — regime-to-weather mapping
// ---------------------------------------------------------------------------

export const FRONT_TYPES: Record<string, { label: string; color: string; symbol: string }> = {
  trending_up:    { label: 'WARM FRONT', color: '#FF4444', symbol: 'W' },
  trending_down:  { label: 'COLD FRONT', color: '#00FFFF', symbol: 'C' },
  mean_reverting: { label: 'STATIONARY', color: '#FFBF00', symbol: 'S' },
  high_vol_choppy:{ label: 'OCCLUDED', color: '#a855f7', symbol: 'O' },
  low_vol_calm:   { label: 'HIGH PRESSURE', color: '#00FF41', symbol: 'H' },
};

export const SOURCE_LABELS: Record<string, string> = {
  prediction_market: 'PREDICTION MKTS',
  stock: 'EQUITIES',
};

// ---------------------------------------------------------------------------
// Derived computations
// ---------------------------------------------------------------------------

export function computeBeaufort(volatility: number, trendStrength: number, mrScore: number): number {
  const composite = volatility * 0.5 + Math.abs(trendStrength) * 0.25 + Math.abs(mrScore) * 0.25;
  const idx = BEAUFORT_SCALE.findIndex((b) => composite <= b.max);
  return idx >= 0 ? idx : 12;
}

export function isBootstrapReading(reading: MarketReading): boolean {
  return (
    reading.num_markets_sampled === 0
    && reading.confidence <= 0.1
    && reading.volatility === 0
    && reading.trend_strength === 0
    && reading.mean_reversion_score === 0
  );
}

export function computeAdvisory(readings: MarketReading[]): AdvisoryLevel {
  const activeReadings = readings.filter((r) => !isBootstrapReading(r));
  if (activeReadings.length === 0) return 'ALL_CLEAR';
  const maxVol = Math.max(...activeReadings.map((r) => r.volatility));
  const maxTrend = Math.max(...activeReadings.map((r) => Math.abs(r.trend_strength)));
  const avgConfidence = activeReadings.reduce((s, r) => s + r.confidence, 0) / activeReadings.length;
  if (maxVol > 0.85 || (maxVol > 0.7 && avgConfidence < 0.3)) return 'STORM_WARNING';
  if (maxVol > 0.65 || (maxTrend > 0.4 && maxVol > 0.4)) return 'GALE_WARNING';
  if (maxVol > 0.35 || maxTrend > 0.25) return 'SMALL_CRAFT';
  return 'ALL_CLEAR';
}

// ---------------------------------------------------------------------------
// Shared response types (used by API route + DecisionAuditPanel)
// ---------------------------------------------------------------------------

export interface RegimeSnapshot {
  regime: string;
  confidence: number;
  volatility: number | null;
  timestamp: string;
  source?: string;
}

export interface StrategyFitnessRow {
  strategy_name: string;
  regime: string;
  fitness_score: number;
  trade_count: number;
  total_pnl_cents: number;
  last_updated?: string;
}

export interface DecisionAuditCycle {
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
    top_fitness: StrategyFitnessRow[];
  };
  outcome: {
    trade_count: number;
    net_pnl_cents: number;
    window_hours: number;
  };
}

// ---------------------------------------------------------------------------
// Anomaly detection
// ---------------------------------------------------------------------------

export interface Anomaly {
  id: string;
  type: 'divergence' | 'regime_transition' | 'confidence_drop';
  severity: 'amber' | 'red';
  message: string;
  timestamp: string;
}

export function detectAnomalies(
  readings: MarketReading[],
  recentRegimes: RegimePoint[],
): Anomaly[] {
  const anomalies: Anomaly[] = [];
  const active = readings.filter((r) => !isBootstrapReading(r));

  // Source divergence
  if (active.length >= 2) {
    const regimes = new Set(active.map((r) => r.regime));
    if (regimes.size > 1) {
      const confGap = Math.abs(active[0].confidence - active[1].confidence);
      anomalies.push({
        id: 'divergence',
        type: 'divergence',
        severity: confGap > 0.2 ? 'red' : 'amber',
        message: `SOURCE DIVERGENCE: ${active.map((r) => `${SOURCE_LABELS[r.source] ?? r.source}=${r.regime.replace(/_/g, ' ').toUpperCase()}`).join(' vs ')}`,
        timestamp: active[0].timestamp,
      });
    }
  }

  // Regime transition in last hour
  if (recentRegimes.length >= 2) {
    const oneHourAgo = Date.now() - 60 * 60 * 1000;
    for (let i = 1; i < recentRegimes.length; i++) {
      if (
        recentRegimes[i].regime !== recentRegimes[i - 1].regime &&
        new Date(recentRegimes[i].timestamp).getTime() > oneHourAgo
      ) {
        anomalies.push({
          id: `transition-${i}`,
          type: 'regime_transition',
          severity: 'amber',
          message: `REGIME SHIFT: ${recentRegimes[i - 1].regime.replace(/_/g, ' ').toUpperCase()} -> ${recentRegimes[i].regime.replace(/_/g, ' ').toUpperCase()}`,
          timestamp: recentRegimes[i].timestamp,
        });
        break; // only show most recent transition
      }
    }
  }

  // Confidence drop
  for (const r of active) {
    if (r.confidence < 0.25) {
      anomalies.push({
        id: `conf-${r.source}`,
        type: 'confidence_drop',
        severity: 'red',
        message: `LOW CONFIDENCE: ${SOURCE_LABELS[r.source] ?? r.source} at ${(r.confidence * 100).toFixed(0)}%`,
        timestamp: r.timestamp,
      });
    } else if (r.confidence < 0.4) {
      anomalies.push({
        id: `conf-${r.source}`,
        type: 'confidence_drop',
        severity: 'amber',
        message: `CONFIDENCE FALLING: ${SOURCE_LABELS[r.source] ?? r.source} at ${(r.confidence * 100).toFixed(0)}%`,
        timestamp: r.timestamp,
      });
    }
  }

  return anomalies;
}
