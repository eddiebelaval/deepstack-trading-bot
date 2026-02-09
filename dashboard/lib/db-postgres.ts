import { restGet, restInsert, restUpsert, restUpdate } from './postgres';
import {
  Trade,
  DailySummary,
  LogEntry,
  StrategyStatus,
  DashboardState,
  Opportunity,
  MarketSnapshot,
  PerformanceMetric,
  TradingStats,
  BotCommand,
  BotConfig,
  Position,
  Order,
  Fill,
} from './types';

// PostgREST uses URL query params for filtering/sorting.
// Docs: https://postgrest.org/en/stable/references/api/tables_views.html

// ============================================================================
// TRADES
// ============================================================================

export async function getRecentTrades(limit: number = 20): Promise<Trade[]> {
  return restGet<Trade>('deepstack_trades', `order=created_at.desc&limit=${limit}`);
}

export async function getTodayTrades(): Promise<Trade[]> {
  const today = new Date().toISOString().split('T')[0];
  return restGet<Trade>('deepstack_trades', `session_date=eq.${today}&order=created_at.desc`);
}

export async function getActivePositions(): Promise<Trade[]> {
  return restGet<Trade>('deepstack_trades', `status=eq.open&order=created_at.desc`);
}

export async function createTrade(trade: Omit<Trade, 'id' | 'created_at' | 'updated_at'>): Promise<Trade> {
  return restInsert<Trade>('deepstack_trades', {
    market_ticker: trade.market_ticker,
    side: trade.side,
    action: trade.action,
    contracts: trade.contracts,
    entry_price_cents: trade.entry_price_cents,
    fill_price_cents: trade.fill_price_cents,
    exit_price_cents: trade.exit_price_cents,
    pnl_cents: trade.pnl_cents,
    order_id: trade.order_id,
    exit_order_id: trade.exit_order_id,
    status: trade.status,
    reasoning: trade.reasoning,
    exit_reason: trade.exit_reason,
    strategy: trade.strategy,
    session_date: trade.session_date,
    metadata: trade.metadata || null,
  });
}

export async function updateTrade(id: string, updates: Partial<Trade>): Promise<Trade | null> {
  const allowed = ['fill_price_cents', 'exit_price_cents', 'pnl_cents', 'exit_order_id', 'status', 'exit_reason', 'metadata'];
  const body: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(updates)) {
    if (allowed.includes(key)) body[key] = value;
  }
  if (Object.keys(body).length === 0) return null;
  return restUpdate<Trade>('deepstack_trades', `id=eq.${id}`, body);
}

// ============================================================================
// DAILY SUMMARY
// ============================================================================

export async function getDailySummary(date?: string): Promise<DailySummary | null> {
  const targetDate = date || new Date().toISOString().split('T')[0];
  const rows = await restGet<DailySummary>('deepstack_daily_summary', `date=eq.${targetDate}`);
  return rows[0] || null;
}

export async function getRecentSummaries(limit: number = 7): Promise<DailySummary[]> {
  return restGet<DailySummary>('deepstack_daily_summary', `order=date.desc&limit=${limit}`);
}

export async function upsertDailySummary(summary: Omit<DailySummary, 'id' | 'created_at'>): Promise<DailySummary> {
  return restUpsert<DailySummary>('deepstack_daily_summary', {
    date: summary.date,
    total_trades: summary.total_trades,
    winning_trades: summary.winning_trades,
    losing_trades: summary.losing_trades,
    gross_pnl_cents: summary.gross_pnl_cents,
    fees_cents: summary.fees_cents,
    net_pnl_cents: summary.net_pnl_cents,
    largest_win_cents: summary.largest_win_cents,
    largest_loss_cents: summary.largest_loss_cents,
    avg_winner_cents: summary.avg_winner_cents,
    avg_loser_cents: summary.avg_loser_cents,
    max_contracts: summary.max_contracts,
    starting_balance_cents: summary.starting_balance_cents,
    ending_balance_cents: summary.ending_balance_cents,
    notes: summary.notes,
  }, 'date');
}

// ============================================================================
// STRATEGY STATS
// ============================================================================

// PostgREST can't do aggregations natively, so we use Supabase RPC or
// compute stats client-side from the trades table.

const DEFAULT_STATS: TradingStats = { total_trades: 0, winning_trades: 0, total_pnl_cents: 0 };

export async function getStrategyStats(strategy: string): Promise<TradingStats> {
  const trades = await restGet<Trade>(
    'deepstack_trades',
    `strategy=eq.${strategy}&status=eq.closed&select=pnl_cents`
  );
  if (trades.length === 0) return DEFAULT_STATS;

  return {
    total_trades: trades.length,
    winning_trades: trades.filter(t => (t.pnl_cents ?? 0) > 0).length,
    total_pnl_cents: trades.reduce((sum, t) => sum + (t.pnl_cents ?? 0), 0),
  };
}

export async function getAllStrategyStats(): Promise<Record<string, TradingStats>> {
  const trades = await restGet<Trade>(
    'deepstack_trades',
    `status=eq.closed&select=strategy,pnl_cents`
  );

  const statsMap: Record<string, TradingStats> = {};
  for (const trade of trades) {
    if (!statsMap[trade.strategy]) {
      statsMap[trade.strategy] = { total_trades: 0, winning_trades: 0, total_pnl_cents: 0 };
    }
    statsMap[trade.strategy].total_trades++;
    if ((trade.pnl_cents ?? 0) > 0) statsMap[trade.strategy].winning_trades++;
    statsMap[trade.strategy].total_pnl_cents += trade.pnl_cents ?? 0;
  }
  return statsMap;
}

export async function getTotalStats(): Promise<TradingStats & { active_positions?: number }> {
  const trades = await restGet<Trade>(
    'deepstack_trades',
    `status=in.(closed,open)&select=pnl_cents,status`
  );

  const closed = trades.filter(t => t.status === 'closed');
  const open = trades.filter(t => t.status === 'open');

  return {
    total_trades: closed.length,
    winning_trades: closed.filter(t => (t.pnl_cents ?? 0) > 0).length,
    total_pnl_cents: closed.reduce((sum, t) => sum + (t.pnl_cents ?? 0), 0),
    active_positions: open.length,
  };
}

// ============================================================================
// OPPORTUNITIES
// ============================================================================

export async function getOpportunities(status?: string, limit: number = 50): Promise<Opportunity[]> {
  let params = `order=created_at.desc&limit=${limit}`;
  if (status && status !== 'all') {
    params = `status=eq.${status}&${params}`;
  }
  return restGet<Opportunity>('deepstack_opportunities', params);
}

export async function createOpportunity(opp: Omit<Opportunity, 'id' | 'created_at' | 'taken_at' | 'expired_at' | 'trade_id'>): Promise<Opportunity> {
  return restInsert<Opportunity>('deepstack_opportunities', {
    market_ticker: opp.market_ticker,
    strategy: opp.strategy,
    side: opp.side,
    current_price_cents: opp.current_price_cents,
    target_price_cents: opp.target_price_cents,
    expected_profit_pct: opp.expected_profit_pct,
    confidence: opp.confidence,
    status: opp.status,
    reasoning: opp.reasoning,
  });
}

export async function updateOpportunityStatus(
  id: string,
  status: 'taken' | 'expired' | 'rejected',
  tradeId?: number
): Promise<Opportunity | null> {
  const body: Record<string, unknown> = { status };
  if (status === 'taken') body.taken_at = new Date().toISOString();
  else body.expired_at = new Date().toISOString();
  if (tradeId) body.trade_id = tradeId;
  return restUpdate<Opportunity>('deepstack_opportunities', `id=eq.${id}`, body);
}

// ============================================================================
// DASHBOARD STATE
// ============================================================================

export async function saveDashboardState(state: DashboardState): Promise<void> {
  await restInsert('deepstack_dashboard_state', {
    timestamp: state.timestamp,
    balance_cents: state.account.balance_cents,
    daily_pnl_cents: state.account.daily_pnl_cents,
    daily_pnl_percentage: state.account.daily_pnl_percentage,
    total_positions: state.account.total_positions,
    available_balance_cents: state.account.available_balance_cents,
    daily_loss_limit_cents: state.risk.daily_loss_limit_cents,
    daily_loss_used_cents: state.risk.daily_loss_used_cents,
    max_position_size_cents: state.risk.max_position_size_cents,
    kelly_fraction: state.risk.kelly_fraction,
    positions_at_risk: state.risk.positions_at_risk,
    risk_percentage: state.risk.risk_percentage,
  });
}

export async function getLatestDashboardState(): Promise<DashboardState | null> {
  const rows = await restGet<{
    timestamp: string;
    balance_cents: number;
    daily_pnl_cents: number;
    daily_pnl_percentage: number;
    total_positions: number;
    available_balance_cents: number;
    daily_loss_limit_cents: number;
    daily_loss_used_cents: number;
    max_position_size_cents: number;
    kelly_fraction: number;
    positions_at_risk: number;
    risk_percentage: number;
  }>('deepstack_dashboard_state', 'order=timestamp.desc&limit=1');

  if (rows.length === 0) return null;

  const row = rows[0];
  const strategies = await restGet<StrategyStatus>(
    'deepstack_strategy_status',
    'select=name,enabled,active_positions,opportunities_found,last_scan,status&order=name'
  );

  return {
    timestamp: row.timestamp,
    account: {
      balance_cents: row.balance_cents,
      daily_pnl_cents: row.daily_pnl_cents,
      daily_pnl_percentage: row.daily_pnl_percentage,
      total_positions: row.total_positions,
      available_balance_cents: row.available_balance_cents,
    },
    risk: {
      daily_loss_limit_cents: row.daily_loss_limit_cents,
      daily_loss_used_cents: row.daily_loss_used_cents,
      max_position_size_cents: row.max_position_size_cents,
      kelly_fraction: row.kelly_fraction,
      positions_at_risk: row.positions_at_risk,
      risk_percentage: row.risk_percentage,
    },
    strategies,
  };
}

// ============================================================================
// STRATEGY STATUS
// ============================================================================

export async function getStrategies(): Promise<StrategyStatus[]> {
  return restGet<StrategyStatus>(
    'deepstack_strategy_status',
    'select=name,enabled,active_positions,opportunities_found,last_scan,status&order=name'
  );
}

export async function updateStrategyStatus(
  name: string,
  updates: Partial<Omit<StrategyStatus, 'name'>>
): Promise<StrategyStatus | null> {
  const allowed = ['enabled', 'active_positions', 'opportunities_found', 'last_scan', 'status'];
  const body: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(updates)) {
    if (allowed.includes(key)) body[key] = value;
  }
  if (Object.keys(body).length === 0) return null;
  return restUpdate<StrategyStatus>('deepstack_strategy_status', `name=eq.${name}`, body);
}

// ============================================================================
// LOG ENTRIES
// ============================================================================

export async function getRecentLogs(limit: number = 50): Promise<LogEntry[]> {
  const logs = await restGet<LogEntry>(
    'deepstack_log_entries',
    `select=timestamp,level,strategy,message&order=timestamp.desc&limit=${limit}`
  );
  return logs.reverse();
}

export async function createLogEntry(entry: Omit<LogEntry, 'id'>): Promise<void> {
  await restInsert('deepstack_log_entries', {
    level: entry.level,
    strategy: entry.strategy,
    message: entry.message,
  });
}

// ============================================================================
// MARKET SNAPSHOTS
// ============================================================================

export async function saveMarketSnapshot(snapshot: Omit<MarketSnapshot, 'id' | 'timestamp'>): Promise<void> {
  await restInsert('deepstack_market_snapshots', {
    market_ticker: snapshot.market_ticker,
    yes_price_cents: snapshot.yes_price_cents,
    no_price_cents: snapshot.no_price_cents,
    volume: snapshot.volume,
    open_interest: snapshot.open_interest,
    last_trade_price_cents: snapshot.last_trade_price_cents,
  });
}

export async function getMarketHistory(ticker: string, limit: number = 100): Promise<MarketSnapshot[]> {
  return restGet<MarketSnapshot>(
    'deepstack_market_snapshots',
    `market_ticker=eq.${ticker}&order=timestamp.desc&limit=${limit}`
  );
}

// ============================================================================
// BALANCE HISTORY (for charts)
// ============================================================================

export async function getBalanceHistory(limit: number = 200): Promise<{ timestamp: string; balance_cents: number; available_balance_cents: number }[]> {
  return restGet<{ timestamp: string; balance_cents: number; available_balance_cents: number }>(
    'deepstack_dashboard_state',
    `select=timestamp,balance_cents,available_balance_cents&order=timestamp.desc&limit=${limit}`
  );
}

export async function getOpenPositionsByStrategy(): Promise<Record<string, number>> {
  const trades = await restGet<{ strategy: string }>(
    'deepstack_trades',
    'status=eq.open&select=strategy'
  );
  const counts: Record<string, number> = {};
  for (const t of trades) {
    counts[t.strategy] = (counts[t.strategy] || 0) + 1;
  }
  return counts;
}

// ============================================================================
// PERFORMANCE METRICS
// ============================================================================

export async function getPerformanceMetrics(
  periodType: 'hourly' | 'daily' | 'weekly' | 'monthly',
  strategy?: string,
  limit: number = 30
): Promise<PerformanceMetric[]> {
  let params = `period_type=eq.${periodType}`;
  if (strategy) params += `&strategy=eq.${strategy}`;
  params += `&order=period_start.desc&limit=${limit}`;
  return restGet<PerformanceMetric>('deepstack_performance_metrics', params);
}

// ============================================================================
// BOT COMMANDS (Control Plane)
// ============================================================================

export async function createCommand(command: string, params: Record<string, unknown> = {}): Promise<BotCommand> {
  return restInsert<BotCommand>('deepstack_bot_commands', {
    command,
    params,
    created_by: 'dashboard',
  });
}

export async function getRecentCommands(limit: number = 20): Promise<BotCommand[]> {
  return restGet<BotCommand>('deepstack_bot_commands', `order=created_at.desc&limit=${limit}`);
}

// ============================================================================
// BOT CONFIG (Control Plane)
// ============================================================================

export async function getBotConfig(): Promise<BotConfig | null> {
  const rows = await restGet<BotConfig>('deepstack_bot_config', 'id=eq.1');
  return rows[0] || null;
}

export async function updateBotConfig(updates: Partial<BotConfig>): Promise<BotConfig | null> {
  const allowed = [
    'mode', 'poll_interval_seconds', 'max_position_size_cents',
    'daily_loss_limit_cents', 'kelly_fraction', 'profile', 'use_grok'
  ];
  const body: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(updates)) {
    if (allowed.includes(key)) body[key] = value;
  }
  if (Object.keys(body).length === 0) return null;
  return restUpdate<BotConfig>('deepstack_bot_config', 'id=eq.1', body);
}

// ============================================================================
// POSITIONS (Kalshi portfolio positions, synced by bot)
// ============================================================================

export async function getPositions(): Promise<Position[]> {
  return restGet<Position>('deepstack_positions', 'order=synced_at.desc');
}

// ============================================================================
// ORDERS (Kalshi orders, synced by bot)
// ============================================================================

export async function getOrders(status?: string): Promise<Order[]> {
  let params = 'order=synced_at.desc';
  if (status) params += `&status=eq.${status}`;
  return restGet<Order>('deepstack_orders', params);
}

// ============================================================================
// FILLS (Kalshi execution history, synced by bot)
// ============================================================================

export async function getFills(limit: number = 100): Promise<Fill[]> {
  return restGet<Fill>('deepstack_fills', `order=created_time.desc&limit=${limit}`);
}
