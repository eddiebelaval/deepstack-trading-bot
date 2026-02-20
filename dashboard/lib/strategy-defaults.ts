/**
 * Default config values for all 13 strategies.
 * Mirrors the Python bot's config.yaml so the dashboard can show
 * sensible defaults without needing to parse YAML at runtime.
 */

export type StrategyConfig = Record<string, number | boolean | string>;

/** Universal defaults applied to every strategy */
const UNIVERSAL_DEFAULTS: StrategyConfig = {
  take_profit_cents: 5,
  stop_loss_cents: 3,
  min_volume: 500,
};

export const STRATEGY_DEFAULTS: Record<string, StrategyConfig> = {
  mean_reversion: {
    ...UNIVERSAL_DEFAULTS,
    lookback_periods: 20,
    mean_threshold: 5,
  },
  momentum: {
    ...UNIVERSAL_DEFAULTS,
    lookback_periods: 15,
    momentum_threshold: 3,
    reversal_threshold: 2,
  },
  combinatorial_arbitrage: {
    ...UNIVERSAL_DEFAULTS,
    min_profit_cents: 3,
    max_exposure_per_arb: 50,
    max_spread_cents: 3,
    max_legs: 4,
    confidence_threshold: 0.7,
  },
  cross_platform_arbitrage: {
    ...UNIVERSAL_DEFAULTS,
    price_diff_threshold_cents: 5,
    min_match_score: 0.75,
    min_polymarket_volume: 5000,
  },
  high_probability_bonds: {
    ...UNIVERSAL_DEFAULTS,
    take_profit_cents: 7,
    min_probability_cents: 93,
    max_probability_cents: 98,
    max_hours_to_expiry: 48,
  },
  calibration_edge: {
    ...UNIVERSAL_DEFAULTS,
    min_edge_cents: 3,
    favorite_threshold_cents: 75,
    longshot_threshold_cents: 15,
  },
  weather_aggregation: {
    ...UNIVERSAL_DEFAULTS,
    min_edge_cents: 4,
    min_model_consensus: 0.7,
    max_hours_to_settlement: 24,
  },
  news_sentiment_fade: {
    ...UNIVERSAL_DEFAULTS,
    spike_threshold_cents: 8,
    spike_window_minutes: 30,
    min_volume_surge: 3,
    max_hold_hours: 12,
  },
  correlated_event_arbitrage: {
    ...UNIVERSAL_DEFAULTS,
    min_implication_edge_cents: 4,
    min_match_confidence: 0.8,
    max_legs: 3,
  },
  domain_specialization: {
    ...UNIVERSAL_DEFAULTS,
    min_signal_count: 3,
    min_consensus_score: 0.6,
  },
  crypto_intraday: {
    ...UNIVERSAL_DEFAULTS,
    min_edge_cents: 3,
    max_hold_minutes: 60,
  },
  bear_macro: {
    ...UNIVERSAL_DEFAULTS,
    min_edge_cents: 4,
    bear_mode_only: false,
    max_hold_hours: 72,
  },
  settlement_betting: {
    ...UNIVERSAL_DEFAULTS,
    take_profit_cents: 2,
    stop_loss_cents: 5,
    min_spread_cents: 2,
    max_spread_cents: 8,
    inventory_limit: 20,
    skew_per_contract: 0.5,
  },
  market_making: {
    ...UNIVERSAL_DEFAULTS,
    take_profit_cents: 2,
    stop_loss_cents: 5,
    min_spread_cents: 2,
    max_spread_cents: 8,
    inventory_limit: 20,
    skew_per_contract: 0.5,
  },
};

/** Get defaults for a strategy, falling back to universal only */
export function getStrategyDefaults(name: string): StrategyConfig {
  return STRATEGY_DEFAULTS[name] ?? { ...UNIVERSAL_DEFAULTS };
}

/** Merge defaults with overrides, returning the effective config */
export function mergeConfig(
  defaults: StrategyConfig,
  overrides: StrategyConfig | null | undefined,
): StrategyConfig {
  if (!overrides) return { ...defaults };
  return { ...defaults, ...overrides };
}
