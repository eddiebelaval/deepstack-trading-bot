/**
 * Strategy metadata — single source of truth for display names,
 * descriptions, and categories across all dashboard components.
 */

export type StrategyCategory = 'original' | 'prediction_market';

export interface StrategyMeta {
  /** Full display name */
  displayName: string;
  /** Short name for sidebar (max ~16 chars) */
  shortName: string;
  /** One-line description of the edge */
  description: string;
  /** What type of edge it exploits */
  edgeType: string;
  /** Category grouping */
  category: StrategyCategory;
  /** Expected win rate from backtesting */
  expectedWinRate: number;
}

export const STRATEGY_META: Record<string, StrategyMeta> = {
  // ── Original Strategies ──────────────────────────────
  mean_reversion: {
    displayName: 'Mean Reversion',
    shortName: 'Mean Revert',
    description: 'Buys contracts that deviate from fair value, expecting price to revert toward the mean.',
    edgeType: 'Statistical',
    category: 'original',
    expectedWinRate: 0.54,
  },
  momentum: {
    displayName: 'Momentum',
    shortName: 'Momentum',
    description: 'Follows established price trends, entering in the direction of momentum.',
    edgeType: 'Trend',
    category: 'original',
    expectedWinRate: 0.52,
  },
  combinatorial_arbitrage: {
    displayName: 'Combinatorial Arb',
    shortName: 'Combo Arb',
    description: 'Detects mispriced relationships between related markets using graph analysis.',
    edgeType: 'Structural',
    category: 'original',
    expectedWinRate: 0.60,
  },
  cross_platform_arbitrage: {
    displayName: 'Cross-Platform Arb',
    shortName: 'X-Platform',
    description: 'Exploits price differences between Kalshi and Polymarket on the same events.',
    edgeType: 'Cross-Exchange',
    category: 'original',
    expectedWinRate: 0.58,
  },

  // ── Prediction Market Strategies ─────────────────────
  high_probability_bonds: {
    displayName: 'High-Prob Bonds',
    shortName: 'Hi-Prob Bonds',
    description: 'Buys 93-98c contracts near certain to resolve YES. Collects remaining 2-7c like a bond coupon.',
    edgeType: 'Near-Certainty',
    category: 'prediction_market',
    expectedWinRate: 0.97,
  },
  calibration_edge: {
    displayName: 'Calibration Edge',
    shortName: 'Calibration',
    description: 'Exploits favorite-longshot bias. Markets overprice longshots and underprice favorites.',
    edgeType: 'Behavioral Bias',
    category: 'prediction_market',
    expectedWinRate: 0.58,
  },
  weather_aggregation: {
    displayName: 'Weather Aggregation',
    shortName: 'Weather Agg',
    description: 'Aggregates NWS + Open-Meteo forecasts to beat Kalshi weather market consensus.',
    edgeType: 'Model Consensus',
    category: 'prediction_market',
    expectedWinRate: 0.62,
  },
  news_sentiment_fade: {
    displayName: 'News Sentiment Fade',
    shortName: 'News Fade',
    description: 'Fades overreactions to breaking news. Detects spikes and enters opposite direction.',
    edgeType: 'Overreaction',
    category: 'prediction_market',
    expectedWinRate: 0.55,
  },
  correlated_event_arbitrage: {
    displayName: 'Correlated Event Arb',
    shortName: 'Event Arb',
    description: 'Exploits logical relationship violations. If A implies B, then P(B) must >= P(A).',
    edgeType: 'Logical',
    category: 'prediction_market',
    expectedWinRate: 0.62,
  },
  domain_specialization: {
    displayName: 'Domain Specialist',
    shortName: 'Domain Spec',
    description: 'Meta-strategy with pluggable signals for deep expertise in narrow market categories.',
    edgeType: 'Domain Expert',
    category: 'prediction_market',
    expectedWinRate: 0.56,
  },
};

export const CATEGORY_LABELS: Record<StrategyCategory, string> = {
  original: 'STOCK MARKET',
  prediction_market: 'PREDICTION MARKET',
};

export const CATEGORY_ICONS: Record<StrategyCategory, string> = {
  original: 'S&P',
  prediction_market: 'PM',
};

export function getStrategyMeta(name: string): StrategyMeta {
  return STRATEGY_META[name] ?? {
    displayName: name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
    shortName: name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ').slice(0, 16),
    description: 'Custom strategy',
    edgeType: 'Unknown',
    category: 'original' as StrategyCategory,
    expectedWinRate: 0.50,
  };
}

/** Get all strategy names grouped by category */
export function getStrategiesByCategory(): Record<StrategyCategory, string[]> {
  const groups: Record<StrategyCategory, string[]> = {
    original: [],
    prediction_market: [],
  };

  for (const [name, meta] of Object.entries(STRATEGY_META)) {
    groups[meta.category].push(name);
  }

  return groups;
}
