// Trade data structure matching SQLite schema
export interface Trade {
  id: string;
  created_at: string;
  updated_at: string;
  market_ticker: string;
  side: string;
  action: string;
  contracts: number;
  entry_price_cents: number;
  fill_price_cents: number | null;
  exit_price_cents: number | null;
  pnl_cents: number | null;
  order_id: string | null;
  exit_order_id: string | null;
  status: string;
  reasoning: string | null;
  exit_reason: string | null;
  strategy: string;
  session_date: string | null;
  metadata: string | null;
}

// Daily summary structure
export interface DailySummary {
  date: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  gross_pnl_cents: number;
  fees_cents: number;
  net_pnl_cents: number;
  largest_win_cents: number;
  largest_loss_cents: number;
  avg_winner_cents: number;
  avg_loser_cents: number;
  max_contracts: number;
  starting_balance_cents: number | null;
  ending_balance_cents: number | null;
  notes: string | null;
}

// Strategy status for dashboard
export interface StrategyStatus {
  name: string;
  enabled: boolean;
  active_positions: number;
  opportunities_found: number;
  last_scan: string | null;
  status: 'active' | 'inactive' | 'scanning' | 'error';
}

// Alias for components that use Strategy
export type Strategy = StrategyStatus;

// Live feed log entry
export interface LogEntry {
  timestamp: string;
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG';
  strategy: string | null;
  message: string;
}

// Account metrics
export interface AccountMetrics {
  balance_cents: number;
  daily_pnl_cents: number;
  daily_pnl_percentage: number;
  total_positions: number;
  available_balance_cents: number;
}

// Risk metrics
export interface RiskMetrics {
  daily_loss_limit_cents: number;
  daily_loss_used_cents: number;
  max_position_size_cents: number;
  kelly_fraction: number;
  positions_at_risk: number;
  risk_percentage: number;
}

// Dashboard state (written by bot)
export interface DashboardState {
  timestamp: string;
  account: AccountMetrics;
  risk: RiskMetrics;
  strategies: StrategyStatus[];
}

// Trading opportunity detected by strategies
export interface Opportunity {
  id: string;
  created_at: string;
  market_ticker: string;
  strategy: string;
  side: 'YES' | 'NO';
  current_price_cents: number;
  target_price_cents: number;
  expected_profit_pct: number;
  confidence: number;
  status: 'active' | 'taken' | 'expired' | 'rejected';
  reasoning: string | null;
  taken_at: string | null;
  expired_at: string | null;
  trade_id: number | null;
}

// Market snapshot for price history
export interface MarketSnapshot {
  id: number;
  timestamp: string;
  market_ticker: string;
  yes_price_cents: number | null;
  no_price_cents: number | null;
  volume: number | null;
  open_interest: number | null;
  last_trade_price_cents: number | null;
}

// Performance metrics aggregated by period
export interface PerformanceMetric {
  period_start: string;
  period_end: string;
  period_type: 'hourly' | 'daily' | 'weekly' | 'monthly';
  strategy: string | null;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  net_pnl_cents: number;
  win_rate: number;
  avg_win_cents: number;
  avg_loss_cents: number;
}

// Aggregated trading stats
export interface TradingStats {
  total_trades: number;
  winning_trades: number;
  total_pnl_cents: number;
  active_positions?: number;
}

// Bot command types for the control plane
export type BotCommandType =
  | 'start'
  | 'stop'
  | 'shutdown'
  | 'pause'
  | 'resume'
  | 'toggle_strategy'
  | 'update_risk'
  | 'force_close'
  | 'switch_profile'
  | 'set_mode'
  | 'scan_now'
  | 'place_trade'
  | 'set_poll_interval';

export type BotCommandStatus = 'pending' | 'acknowledged' | 'executed' | 'failed';

export interface BotCommand {
  id: string;
  command: BotCommandType;
  params: Record<string, unknown>;
  status: BotCommandStatus;
  result: Record<string, unknown> | null;
  created_at: string;
  executed_at: string | null;
  created_by: string;
}

export type BotMode = 'running' | 'stopped' | 'paused' | 'dry_run';

export interface BotConfig {
  id: number;
  mode: BotMode;
  poll_interval_seconds: number;
  max_position_size_cents: number;
  daily_loss_limit_cents: number;
  kelly_fraction: number;
  strategies: StrategyStatus[];
  profile: string;
  use_grok: boolean;
  last_heartbeat: string | null;
  updated_at: string;
}
