/**
 * Strategy metadata — single source of truth for display names,
 * descriptions, and categories across all dashboard components.
 */

export type StrategyCategory = 'original' | 'prediction_market' | 'crypto';

export type RiskProfile = 'conservative' | 'moderate' | 'aggressive';

export interface ConfigField {
  key: string;
  label: string;
  type: 'number' | 'boolean' | 'select';
  suffix?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string | number; label: string }[];
}

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
  /** 2-3 sentence explanation of the trading logic */
  howItWorks: string;
  /** Risk profile classification */
  riskProfile: RiskProfile;
  /** Editable config fields with validation rules */
  configSchema: ConfigField[];
}

/** Universal config fields shared by all strategies */
const UNIVERSAL_FIELDS: ConfigField[] = [
  { key: 'take_profit_cents', label: 'Take Profit', type: 'number', suffix: 'c', min: 1, max: 50, step: 1 },
  { key: 'stop_loss_cents', label: 'Stop Loss', type: 'number', suffix: 'c', min: 1, max: 50, step: 1 },
  { key: 'min_volume', label: 'Min Volume', type: 'number', min: 0, max: 10000, step: 100 },
];

export const STRATEGY_META: Record<string, StrategyMeta> = {
  // ── Original Strategies ──────────────────────────────
  mean_reversion: {
    displayName: 'Mean Reversion',
    shortName: 'Mean Revert',
    description: 'Buys contracts that deviate from fair value, expecting price to revert toward the mean.',
    edgeType: 'Statistical',
    category: 'original',
    expectedWinRate: 0.54,
    howItWorks: 'Calculates a rolling fair-value estimate over a lookback window, then enters when the current price deviates beyond a configurable threshold. Exits when price reverts toward the mean or hits the stop loss.',
    riskProfile: 'moderate',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'lookback_periods', label: 'Lookback Periods', type: 'number', min: 5, max: 100, step: 1 },
      { key: 'mean_threshold', label: 'Mean Threshold', type: 'number', suffix: 'c', min: 1, max: 20, step: 1 },
    ],
  },
  momentum: {
    displayName: 'Momentum',
    shortName: 'Momentum',
    description: 'Follows established price trends, entering in the direction of momentum.',
    edgeType: 'Trend',
    category: 'original',
    expectedWinRate: 0.52,
    howItWorks: 'Measures price momentum over a lookback window and enters when momentum exceeds a threshold. Includes a reversal threshold to exit early if the trend flips before the take-profit target.',
    riskProfile: 'aggressive',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'lookback_periods', label: 'Lookback Periods', type: 'number', min: 5, max: 100, step: 1 },
      { key: 'momentum_threshold', label: 'Momentum Threshold', type: 'number', suffix: 'c', min: 1, max: 20, step: 1 },
      { key: 'reversal_threshold', label: 'Reversal Threshold', type: 'number', suffix: 'c', min: 1, max: 20, step: 1 },
    ],
  },
  combinatorial_arbitrage: {
    displayName: 'Combinatorial Arb',
    shortName: 'Combo Arb',
    description: 'Detects mispriced relationships between related markets using graph analysis.',
    edgeType: 'Structural',
    category: 'original',
    expectedWinRate: 0.60,
    howItWorks: 'Builds a graph of related markets and searches for multi-leg combinations where the sum of contract prices implies a risk-free profit. Filters by minimum profit, spread, and confidence before entering.',
    riskProfile: 'conservative',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_profit_cents', label: 'Min Profit', type: 'number', suffix: 'c', min: 1, max: 20, step: 1 },
      { key: 'max_exposure_per_arb', label: 'Max Exposure/Arb', type: 'number', suffix: '$', min: 1, max: 500, step: 5 },
      { key: 'max_spread_cents', label: 'Max Spread', type: 'number', suffix: 'c', min: 1, max: 10, step: 1 },
      { key: 'max_legs', label: 'Max Legs', type: 'number', min: 2, max: 6, step: 1 },
      { key: 'confidence_threshold', label: 'Confidence', type: 'number', suffix: '%', min: 0.5, max: 1, step: 0.05 },
    ],
  },
  cross_platform_arbitrage: {
    displayName: 'Cross-Platform Arb',
    shortName: 'X-Platform',
    description: 'Exploits price differences between Kalshi and Polymarket on the same events.',
    edgeType: 'Cross-Exchange',
    category: 'original',
    expectedWinRate: 0.58,
    howItWorks: 'Matches events across Kalshi and Polymarket using fuzzy title matching, then enters when the price difference exceeds a threshold. Requires minimum volume on the Polymarket side to ensure liquidity.',
    riskProfile: 'moderate',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'price_diff_threshold_cents', label: 'Price Diff Threshold', type: 'number', suffix: 'c', min: 1, max: 20, step: 1 },
      { key: 'min_match_score', label: 'Min Match Score', type: 'number', suffix: '%', min: 0.5, max: 1, step: 0.05 },
      { key: 'min_polymarket_volume', label: 'Min Poly Volume', type: 'number', suffix: '$', min: 100, max: 100000, step: 100 },
    ],
  },

  // ── Prediction Market Strategies ─────────────────────
  high_probability_bonds: {
    displayName: 'High-Prob Bonds',
    shortName: 'Hi-Prob Bonds',
    description: 'Buys 93-98c contracts near certain to resolve YES. Collects remaining 2-7c like a bond coupon.',
    edgeType: 'Near-Certainty',
    category: 'prediction_market',
    expectedWinRate: 0.97,
    howItWorks: 'Scans for contracts priced between configurable probability bounds (e.g. 93-98c) that are close to expiry. The edge is the coupon: buying at 95c and collecting 100c on resolution. Risk is the rare tail event where the contract resolves NO.',
    riskProfile: 'conservative',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_probability_cents', label: 'Min Probability', type: 'number', suffix: 'c', min: 85, max: 99, step: 1 },
      { key: 'max_probability_cents', label: 'Max Probability', type: 'number', suffix: 'c', min: 90, max: 99, step: 1 },
      { key: 'max_hours_to_expiry', label: 'Max Hours to Expiry', type: 'number', suffix: 'h', min: 1, max: 168, step: 1 },
    ],
  },
  calibration_edge: {
    displayName: 'Calibration Edge',
    shortName: 'Calibration',
    description: 'Exploits favorite-longshot bias. Markets overprice longshots and underprice favorites.',
    edgeType: 'Behavioral Bias',
    category: 'prediction_market',
    expectedWinRate: 0.58,
    howItWorks: 'Detects the favorite-longshot bias where bettors overpay for longshots and underpay for favorites. Buys underpriced favorites and sells overpriced longshots based on configurable edge thresholds.',
    riskProfile: 'moderate',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_edge_cents', label: 'Min Edge', type: 'number', suffix: 'c', min: 1, max: 15, step: 1 },
      { key: 'favorite_threshold_cents', label: 'Favorite Threshold', type: 'number', suffix: 'c', min: 60, max: 95, step: 1 },
      { key: 'longshot_threshold_cents', label: 'Longshot Threshold', type: 'number', suffix: 'c', min: 5, max: 40, step: 1 },
    ],
  },
  weather_aggregation: {
    displayName: 'Weather Aggregation',
    shortName: 'Weather Agg',
    description: 'Aggregates NWS + Open-Meteo forecasts to beat Kalshi weather market consensus.',
    edgeType: 'Model Consensus',
    category: 'prediction_market',
    expectedWinRate: 0.62,
    howItWorks: 'Pulls forecasts from NWS and Open-Meteo, weights them by historical accuracy, and compares the consensus probability against the Kalshi market price. Enters when the edge exceeds the minimum and model consensus is strong.',
    riskProfile: 'moderate',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_edge_cents', label: 'Min Edge', type: 'number', suffix: 'c', min: 1, max: 15, step: 1 },
      { key: 'min_model_consensus', label: 'Min Consensus', type: 'number', suffix: '%', min: 0.5, max: 1, step: 0.05 },
      { key: 'max_hours_to_settlement', label: 'Max Hours to Settle', type: 'number', suffix: 'h', min: 1, max: 72, step: 1 },
    ],
  },
  news_sentiment_fade: {
    displayName: 'News Sentiment Fade',
    shortName: 'News Fade',
    description: 'Fades overreactions to breaking news. Detects spikes and enters opposite direction.',
    edgeType: 'Overreaction',
    category: 'prediction_market',
    expectedWinRate: 0.55,
    howItWorks: 'Monitors market prices for sudden spikes within a time window. When a spike exceeds the threshold and volume surges, it enters the opposite direction, betting that the overreaction will revert. Holds for a configurable max duration.',
    riskProfile: 'aggressive',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'spike_threshold_cents', label: 'Spike Threshold', type: 'number', suffix: 'c', min: 3, max: 30, step: 1 },
      { key: 'spike_window_minutes', label: 'Spike Window', type: 'number', suffix: 'min', min: 5, max: 120, step: 5 },
      { key: 'min_volume_surge', label: 'Min Volume Surge', type: 'number', suffix: 'x', min: 1.5, max: 10, step: 0.5 },
      { key: 'max_hold_hours', label: 'Max Hold', type: 'number', suffix: 'h', min: 1, max: 48, step: 1 },
    ],
  },
  correlated_event_arbitrage: {
    displayName: 'Correlated Event Arb',
    shortName: 'Event Arb',
    description: 'Exploits logical relationship violations. If A implies B, then P(B) must >= P(A).',
    edgeType: 'Logical',
    category: 'prediction_market',
    expectedWinRate: 0.62,
    howItWorks: 'Maps logical implications between events (e.g. "Fed cuts 50bp" implies "Fed cuts at all"). When the implied event is priced lower than the more specific event, enters the arbitrage. Can trade multi-leg combinations.',
    riskProfile: 'conservative',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_implication_edge_cents', label: 'Min Impl. Edge', type: 'number', suffix: 'c', min: 1, max: 15, step: 1 },
      { key: 'min_match_confidence', label: 'Match Confidence', type: 'number', suffix: '%', min: 0.5, max: 1, step: 0.05 },
      { key: 'max_legs', label: 'Max Legs', type: 'number', min: 2, max: 6, step: 1 },
    ],
  },
  domain_specialization: {
    displayName: 'Domain Specialist',
    shortName: 'Domain Spec',
    description: 'Meta-strategy with pluggable signals for deep expertise in narrow market categories.',
    edgeType: 'Domain Expert',
    category: 'prediction_market',
    expectedWinRate: 0.56,
    howItWorks: 'A meta-strategy that aggregates pluggable domain-specific signals (e.g. election polls, economic indicators). Enters when enough signals agree and the consensus score exceeds the threshold.',
    riskProfile: 'moderate',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_signal_count', label: 'Min Signals', type: 'number', min: 1, max: 10, step: 1 },
      { key: 'min_consensus_score', label: 'Min Consensus', type: 'number', suffix: '%', min: 0.3, max: 1, step: 0.05 },
    ],
  },

  // ── Crypto Strategies ───────────────────────────────────
  crypto_intraday: {
    displayName: 'Crypto Intraday',
    shortName: 'Crypto Intra',
    description: 'Short-timeframe crypto trading using CoinGecko price feeds, fair value estimation, and volatility harvest.',
    edgeType: 'External Data',
    category: 'crypto',
    expectedWinRate: 0.58,
    howItWorks: 'Uses CoinGecko price feeds to estimate fair value for crypto contracts on Kalshi. Enters when the Kalshi price deviates from the fair value by more than the minimum edge. Short hold times reduce exposure to crypto volatility.',
    riskProfile: 'aggressive',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_edge_cents', label: 'Min Edge', type: 'number', suffix: 'c', min: 1, max: 15, step: 1 },
      { key: 'max_hold_minutes', label: 'Max Hold', type: 'number', suffix: 'min', min: 5, max: 240, step: 5 },
    ],
  },
  market_making: {
    displayName: 'Market Making',
    shortName: 'Market Maker',
    description: 'Non-directional spread capture via two-sided quoting with inventory management.',
    edgeType: 'Liquidity',
    category: 'crypto',
    expectedWinRate: 0.70,
    howItWorks: 'Places both buy and sell limit orders around the mid-price, capturing the bid-ask spread. Manages inventory risk by skewing quotes when position size grows, using a configurable skew factor per contract held.',
    riskProfile: 'moderate',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_spread_cents', label: 'Min Spread', type: 'number', suffix: 'c', min: 1, max: 10, step: 1 },
      { key: 'max_spread_cents', label: 'Max Spread', type: 'number', suffix: 'c', min: 2, max: 20, step: 1 },
      { key: 'inventory_limit', label: 'Inventory Limit', type: 'number', min: 1, max: 100, step: 1 },
      { key: 'skew_per_contract', label: 'Skew/Contract', type: 'number', suffix: 'c', min: 0.1, max: 5, step: 0.1 },
    ],
  },

  // ── Macro Strategies ───────────────────────────────────
  bear_macro: {
    displayName: 'Bear Market Macro',
    shortName: 'Bear Macro',
    description: 'Trades economic indicator markets (Fed rate, CPI, GDP, jobs) using FRED data with regime detection.',
    edgeType: 'Macro Fundamental',
    category: 'prediction_market',
    expectedWinRate: 0.58,
    howItWorks: 'Pulls economic data from FRED (Federal Reserve Economic Data) and uses regime detection to identify bear market conditions. When in bear mode, enters macro indicator contracts (rate decisions, CPI, GDP, jobs) where the market underestimates bearish outcomes.',
    riskProfile: 'aggressive',
    configSchema: [
      ...UNIVERSAL_FIELDS,
      { key: 'min_edge_cents', label: 'Min Edge', type: 'number', suffix: 'c', min: 1, max: 15, step: 1 },
      { key: 'bear_mode_only', label: 'Bear Mode Only', type: 'boolean' },
      { key: 'max_hold_hours', label: 'Max Hold', type: 'number', suffix: 'h', min: 1, max: 168, step: 1 },
    ],
  },
};

export const CATEGORY_LABELS: Record<StrategyCategory, string> = {
  original: 'STOCK MARKET',
  prediction_market: 'PREDICTION MARKET',
  crypto: 'CRYPTO',
};

export const CATEGORY_ICONS: Record<StrategyCategory, string> = {
  original: 'S&P',
  prediction_market: 'PM',
  crypto: 'BTC',
};

export function getStrategyMeta(name: string): StrategyMeta {
  return STRATEGY_META[name] ?? {
    displayName: name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
    shortName: name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ').slice(0, 16),
    description: 'Custom strategy',
    edgeType: 'Unknown',
    category: 'original' as StrategyCategory,
    expectedWinRate: 0.50,
    howItWorks: 'Custom strategy with no additional documentation.',
    riskProfile: 'moderate' as RiskProfile,
    configSchema: [...UNIVERSAL_FIELDS],
  };
}

/** Re-export universal fields for use in defaults */
export { UNIVERSAL_FIELDS };

/** Get all strategy names grouped by category */
export function getStrategiesByCategory(): Record<StrategyCategory, string[]> {
  const groups: Record<StrategyCategory, string[]> = {
    original: [],
    prediction_market: [],
    crypto: [],
  };

  for (const [name, meta] of Object.entries(STRATEGY_META)) {
    groups[meta.category].push(name);
  }

  return groups;
}
