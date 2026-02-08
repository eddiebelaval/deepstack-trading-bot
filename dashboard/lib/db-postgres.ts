import crypto from 'node:crypto';

import { query } from './postgres';
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
} from './types';
import { buildSignedCommandParams, getCommandHmacSecret } from './command-signing';

// Server-only Postgres access (used by Next.js route handlers).

// ============================================================================
// TRADES
// ============================================================================

const TRADE_SELECT = `
  id::text as id,
  created_at::text,
  updated_at::text,
  market_ticker,
  side,
  action,
  contracts,
  entry_price_cents,
  fill_price_cents,
  exit_price_cents,
  pnl_cents,
  order_id,
  exit_order_id,
  status,
  reasoning,
  exit_reason,
  strategy,
  session_date::text as session_date,
  metadata::text as metadata
`;

export async function getRecentTrades(limit: number = 20): Promise<Trade[]> {
  const { rows } = await query<Trade>(
    `select ${TRADE_SELECT} from deepstack_trades order by created_at desc limit $1`,
    [limit]
  );
  return rows;
}

export async function getTodayTrades(): Promise<Trade[]> {
  const today = new Date().toISOString().split('T')[0];
  const { rows } = await query<Trade>(
    `select ${TRADE_SELECT} from deepstack_trades where session_date = $1::date order by created_at desc`,
    [today]
  );
  return rows;
}

export async function getActivePositions(): Promise<Trade[]> {
  const { rows } = await query<Trade>(
    `select ${TRADE_SELECT} from deepstack_trades where status = 'open' order by created_at desc`
  );
  return rows;
}

export async function createTrade(
  trade: Omit<Trade, 'id' | 'created_at' | 'updated_at'>
): Promise<Trade> {
  const { rows } = await query<Trade>(
    `
    insert into deepstack_trades (
      market_ticker, side, action, contracts, entry_price_cents,
      fill_price_cents, exit_price_cents, pnl_cents,
      order_id, exit_order_id, status, reasoning, exit_reason,
      strategy, session_date, metadata
    ) values (
      $1, $2, $3, $4, $5,
      $6, $7, $8,
      $9, $10, $11, $12, $13,
      $14, $15::date, $16::jsonb
    )
    returning ${TRADE_SELECT}
    `,
    [
      trade.market_ticker,
      trade.side,
      trade.action,
      trade.contracts,
      trade.entry_price_cents,
      trade.fill_price_cents ?? null,
      trade.exit_price_cents ?? null,
      trade.pnl_cents ?? null,
      trade.order_id ?? null,
      trade.exit_order_id ?? null,
      trade.status,
      trade.reasoning ?? null,
      trade.exit_reason ?? null,
      trade.strategy,
      trade.session_date ?? null,
      trade.metadata ?? null,
    ]
  );
  return rows[0]!;
}

export async function updateTrade(
  id: string,
  updates: Partial<Trade>
): Promise<Trade | null> {
  const allowed = new Set([
    'fill_price_cents',
    'exit_price_cents',
    'pnl_cents',
    'exit_order_id',
    'status',
    'exit_reason',
    'metadata',
  ]);

  const keys = Object.keys(updates).filter((k) => allowed.has(k));
  if (keys.length === 0) return null;

  const setClauses: string[] = [];
  const params: unknown[] = [];
  keys.forEach((k, idx) => {
    setClauses.push(`${k} = $${idx + 1}`);
    // @ts-expect-error dynamic index
    params.push(updates[k] ?? null);
  });
  params.push(id);

  const { rows } = await query<Trade>(
    `
    update deepstack_trades
    set ${setClauses.join(', ')}
    where id = $${params.length}::int
    returning ${TRADE_SELECT}
    `,
    params
  );
  return rows[0] || null;
}

// ============================================================================
// DAILY SUMMARY
// ============================================================================

export async function getDailySummary(date?: string): Promise<DailySummary | null> {
  const targetDate = date || new Date().toISOString().split('T')[0];
  const { rows } = await query<DailySummary>(
    `
    select
      date::text as date,
      total_trades,
      winning_trades,
      losing_trades,
      gross_pnl_cents,
      fees_cents,
      net_pnl_cents,
      largest_win_cents,
      largest_loss_cents,
      avg_winner_cents,
      avg_loser_cents,
      max_contracts,
      starting_balance_cents,
      ending_balance_cents,
      notes
    from deepstack_daily_summary
    where date = $1::date
    limit 1
    `,
    [targetDate]
  );
  return rows[0] || null;
}

export async function getRecentSummaries(limit: number = 7): Promise<DailySummary[]> {
  const { rows } = await query<DailySummary>(
    `
    select
      date::text as date,
      total_trades,
      winning_trades,
      losing_trades,
      gross_pnl_cents,
      fees_cents,
      net_pnl_cents,
      largest_win_cents,
      largest_loss_cents,
      avg_winner_cents,
      avg_loser_cents,
      max_contracts,
      starting_balance_cents,
      ending_balance_cents,
      notes
    from deepstack_daily_summary
    order by date desc
    limit $1
    `,
    [limit]
  );
  return rows;
}

export async function upsertDailySummary(
  summary: Omit<DailySummary, 'id' | 'created_at'>
): Promise<DailySummary> {
  const { rows } = await query<DailySummary>(
    `
    insert into deepstack_daily_summary (
      date, total_trades, winning_trades, losing_trades,
      gross_pnl_cents, fees_cents, net_pnl_cents,
      largest_win_cents, largest_loss_cents,
      avg_winner_cents, avg_loser_cents,
      max_contracts, starting_balance_cents, ending_balance_cents, notes
    ) values (
      $1::date, $2, $3, $4,
      $5, $6, $7,
      $8, $9,
      $10, $11,
      $12, $13, $14, $15
    )
    on conflict (date) do update set
      total_trades = excluded.total_trades,
      winning_trades = excluded.winning_trades,
      losing_trades = excluded.losing_trades,
      gross_pnl_cents = excluded.gross_pnl_cents,
      fees_cents = excluded.fees_cents,
      net_pnl_cents = excluded.net_pnl_cents,
      largest_win_cents = excluded.largest_win_cents,
      largest_loss_cents = excluded.largest_loss_cents,
      avg_winner_cents = excluded.avg_winner_cents,
      avg_loser_cents = excluded.avg_loser_cents,
      max_contracts = excluded.max_contracts,
      starting_balance_cents = excluded.starting_balance_cents,
      ending_balance_cents = excluded.ending_balance_cents,
      notes = excluded.notes
    returning
      date::text as date,
      total_trades,
      winning_trades,
      losing_trades,
      gross_pnl_cents,
      fees_cents,
      net_pnl_cents,
      largest_win_cents,
      largest_loss_cents,
      avg_winner_cents,
      avg_loser_cents,
      max_contracts,
      starting_balance_cents,
      ending_balance_cents,
      notes
    `,
    [
      summary.date,
      summary.total_trades,
      summary.winning_trades,
      summary.losing_trades,
      summary.gross_pnl_cents,
      summary.fees_cents,
      summary.net_pnl_cents,
      summary.largest_win_cents,
      summary.largest_loss_cents,
      summary.avg_winner_cents,
      summary.avg_loser_cents,
      summary.max_contracts,
      summary.starting_balance_cents ?? null,
      summary.ending_balance_cents ?? null,
      summary.notes ?? null,
    ]
  );
  return rows[0]!;
}

// ============================================================================
// STRATEGY STATS
// ============================================================================

const DEFAULT_STATS: TradingStats = { total_trades: 0, winning_trades: 0, total_pnl_cents: 0 };

export async function getStrategyStats(strategy: string): Promise<TradingStats> {
  const { rows } = await query<{
    total_trades: string;
    winning_trades: string;
    total_pnl_cents: string | null;
  }>(
    `
    select
      count(*) as total_trades,
      sum(case when coalesce(pnl_cents, 0) > 0 then 1 else 0 end) as winning_trades,
      sum(coalesce(pnl_cents, 0)) as total_pnl_cents
    from deepstack_trades
    where strategy = $1 and status = 'closed'
    `,
    [strategy]
  );
  const row = rows[0];
  if (!row) return DEFAULT_STATS;
  return {
    total_trades: Number(row.total_trades || 0),
    winning_trades: Number(row.winning_trades || 0),
    total_pnl_cents: Number(row.total_pnl_cents || 0),
  };
}

export async function getAllStrategyStats(): Promise<Record<string, TradingStats>> {
  const { rows } = await query<{
    strategy: string;
    total_trades: string;
    winning_trades: string;
    total_pnl_cents: string | null;
  }>(
    `
    select
      strategy,
      count(*) as total_trades,
      sum(case when coalesce(pnl_cents, 0) > 0 then 1 else 0 end) as winning_trades,
      sum(coalesce(pnl_cents, 0)) as total_pnl_cents
    from deepstack_trades
    where status = 'closed'
    group by strategy
    `
  );

  const out: Record<string, TradingStats> = {};
  for (const r of rows) {
    out[r.strategy] = {
      total_trades: Number(r.total_trades || 0),
      winning_trades: Number(r.winning_trades || 0),
      total_pnl_cents: Number(r.total_pnl_cents || 0),
    };
  }
  return out;
}

export async function getTotalStats(): Promise<TradingStats & { active_positions?: number }> {
  const { rows } = await query<{
    total_trades: string;
    winning_trades: string;
    total_pnl_cents: string | null;
    active_positions: string;
  }>(
    `
    select
      sum(case when status = 'closed' then 1 else 0 end) as total_trades,
      sum(case when status = 'closed' and coalesce(pnl_cents, 0) > 0 then 1 else 0 end) as winning_trades,
      sum(case when status = 'closed' then coalesce(pnl_cents, 0) else 0 end) as total_pnl_cents,
      sum(case when status = 'open' then 1 else 0 end) as active_positions
    from deepstack_trades
    where status in ('closed', 'open')
    `
  );
  const row = rows[0];
  if (!row) return { ...DEFAULT_STATS, active_positions: 0 };
  return {
    total_trades: Number(row.total_trades || 0),
    winning_trades: Number(row.winning_trades || 0),
    total_pnl_cents: Number(row.total_pnl_cents || 0),
    active_positions: Number(row.active_positions || 0),
  };
}

// ============================================================================
// OPPORTUNITIES
// ============================================================================

export async function getOpportunities(status?: string, limit: number = 50): Promise<Opportunity[]> {
  const params: unknown[] = [];
  let where = '';
  if (status && status !== 'all') {
    params.push(status);
    where = `where status = $${params.length}`;
  }
  params.push(limit);

  const { rows } = await query<Opportunity>(
    `
    select
      id::text as id,
      created_at::text,
      market_ticker,
      strategy,
      side,
      current_price_cents,
      target_price_cents,
      expected_profit_pct,
      confidence,
      status,
      reasoning,
      taken_at::text as taken_at,
      expired_at::text as expired_at,
      trade_id::text as trade_id
    from deepstack_opportunities
    ${where}
    order by created_at desc
    limit $${params.length}
    `,
    params
  );
  return rows;
}

export async function createOpportunity(
  opp: Omit<Opportunity, 'id' | 'created_at' | 'taken_at' | 'expired_at' | 'trade_id'>
): Promise<Opportunity> {
  const { rows } = await query<Opportunity>(
    `
    insert into deepstack_opportunities (
      market_ticker, strategy, side,
      current_price_cents, target_price_cents,
      expected_profit_pct, confidence, status, reasoning
    ) values (
      $1, $2, $3,
      $4, $5,
      $6, $7, $8, $9
    )
    returning
      id::text as id,
      created_at::text,
      market_ticker,
      strategy,
      side,
      current_price_cents,
      target_price_cents,
      expected_profit_pct,
      confidence,
      status,
      reasoning,
      taken_at::text as taken_at,
      expired_at::text as expired_at,
      trade_id::text as trade_id
    `,
    [
      opp.market_ticker,
      opp.strategy,
      opp.side,
      opp.current_price_cents,
      opp.target_price_cents,
      opp.expected_profit_pct,
      opp.confidence,
      opp.status,
      opp.reasoning ?? null,
    ]
  );
  return rows[0]!;
}

export async function updateOpportunityStatus(
  id: string,
  status: 'taken' | 'expired' | 'rejected',
  tradeId?: number
): Promise<Opportunity | null> {
  const now = new Date().toISOString();
  const takenAt = status === 'taken' ? now : null;
  const expiredAt = status !== 'taken' ? now : null;

  const { rows } = await query<Opportunity>(
    `
    update deepstack_opportunities
    set
      status = $1,
      taken_at = coalesce($2::timestamptz, taken_at),
      expired_at = coalesce($3::timestamptz, expired_at),
      trade_id = coalesce($4::int, trade_id)
    where id = $5::int
    returning
      id::text as id,
      created_at::text,
      market_ticker,
      strategy,
      side,
      current_price_cents,
      target_price_cents,
      expected_profit_pct,
      confidence,
      status,
      reasoning,
      taken_at::text as taken_at,
      expired_at::text as expired_at,
      trade_id::text as trade_id
    `,
    [status, takenAt, expiredAt, tradeId ?? null, id]
  );
  return rows[0] || null;
}

// ============================================================================
// DASHBOARD STATE
// ============================================================================

export async function saveDashboardState(state: DashboardState): Promise<void> {
  await query(
    `
    insert into deepstack_dashboard_state (
      timestamp,
      balance_cents,
      daily_pnl_cents,
      daily_pnl_percentage,
      total_positions,
      available_balance_cents,
      daily_loss_limit_cents,
      daily_loss_used_cents,
      max_position_size_cents,
      kelly_fraction,
      positions_at_risk,
      risk_percentage
    ) values (
      $1::timestamptz,
      $2, $3, $4, $5, $6,
      $7, $8, $9, $10, $11, $12
    )
    `,
    [
      state.timestamp,
      state.account.balance_cents,
      state.account.daily_pnl_cents,
      state.account.daily_pnl_percentage,
      state.account.total_positions,
      state.account.available_balance_cents,
      state.risk.daily_loss_limit_cents,
      state.risk.daily_loss_used_cents,
      state.risk.max_position_size_cents,
      state.risk.kelly_fraction,
      state.risk.positions_at_risk,
      state.risk.risk_percentage,
    ]
  );
}

export async function getLatestDashboardState(): Promise<DashboardState | null> {
  const { rows } = await query<{
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
  }>(
    `
    select
      timestamp::text as timestamp,
      balance_cents,
      daily_pnl_cents,
      daily_pnl_percentage,
      total_positions,
      available_balance_cents,
      daily_loss_limit_cents,
      daily_loss_used_cents,
      max_position_size_cents,
      kelly_fraction,
      positions_at_risk,
      risk_percentage
    from deepstack_dashboard_state
    order by timestamp desc
    limit 1
    `
  );

  if (rows.length === 0) return null;
  const row = rows[0];
  const strategies = await getStrategies();

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
  const { rows } = await query<StrategyStatus>(
    `
    select
      name,
      enabled,
      active_positions,
      opportunities_found,
      last_scan::text as last_scan,
      status
    from deepstack_strategy_status
    order by name
    `
  );
  return rows;
}

export async function updateStrategyStatus(
  name: string,
  updates: Partial<Omit<StrategyStatus, 'name'>>
): Promise<StrategyStatus | null> {
  const allowed = new Set(['enabled', 'active_positions', 'opportunities_found', 'last_scan', 'status']);
  const keys = Object.keys(updates).filter((k) => allowed.has(k));
  if (keys.length === 0) return null;

  const setClauses: string[] = [];
  const params: unknown[] = [];
  keys.forEach((k, idx) => {
    setClauses.push(`${k} = $${idx + 1}`);
    // @ts-expect-error dynamic index
    params.push(updates[k] ?? null);
  });
  params.push(name);

  const { rows } = await query<StrategyStatus>(
    `
    update deepstack_strategy_status
    set ${setClauses.join(', ')}
    where name = $${params.length}
    returning
      name,
      enabled,
      active_positions,
      opportunities_found,
      last_scan::text as last_scan,
      status
    `,
    params
  );
  return rows[0] || null;
}

// ============================================================================
// LOG ENTRIES
// ============================================================================

export async function getRecentLogs(limit: number = 50): Promise<LogEntry[]> {
  const { rows } = await query<LogEntry>(
    `
    select
      timestamp::text as timestamp,
      level,
      strategy,
      message
    from deepstack_log_entries
    order by timestamp desc
    limit $1
    `,
    [limit]
  );
  return rows.reverse();
}

export async function createLogEntry(entry: Omit<LogEntry, 'id'>): Promise<void> {
  await query(
    `insert into deepstack_log_entries (timestamp, level, strategy, message) values (coalesce($1::timestamptz, now()), $2, $3, $4)`,
    [entry.timestamp ?? null, entry.level, entry.strategy ?? null, entry.message]
  );
}

// ============================================================================
// MARKET SNAPSHOTS
// ============================================================================

export async function saveMarketSnapshot(snapshot: Omit<MarketSnapshot, 'id' | 'timestamp'>): Promise<void> {
  await query(
    `
    insert into deepstack_market_snapshots (
      market_ticker,
      yes_price_cents,
      no_price_cents,
      volume,
      open_interest,
      last_trade_price_cents
    ) values ($1, $2, $3, $4, $5, $6)
    `,
    [
      snapshot.market_ticker,
      snapshot.yes_price_cents ?? null,
      snapshot.no_price_cents ?? null,
      snapshot.volume ?? null,
      snapshot.open_interest ?? null,
      snapshot.last_trade_price_cents ?? null,
    ]
  );
}

export async function getMarketHistory(ticker: string, limit: number = 100): Promise<MarketSnapshot[]> {
  const { rows } = await query<MarketSnapshot>(
    `
    select
      id,
      timestamp::text as timestamp,
      market_ticker,
      yes_price_cents,
      no_price_cents,
      volume,
      open_interest,
      last_trade_price_cents
    from deepstack_market_snapshots
    where market_ticker = $1
    order by timestamp desc
    limit $2
    `,
    [ticker, limit]
  );
  return rows;
}

// ============================================================================
// PERFORMANCE METRICS
// ============================================================================

export async function getPerformanceMetrics(
  periodType: 'hourly' | 'daily' | 'weekly' | 'monthly',
  strategy?: string,
  limit: number = 30
): Promise<PerformanceMetric[]> {
  const params: unknown[] = [periodType];
  let where = 'where period_type = $1';
  if (strategy) {
    params.push(strategy);
    where += ` and strategy = $${params.length}`;
  }
  params.push(limit);

  const { rows } = await query<PerformanceMetric>(
    `
    select
      period_start::text as period_start,
      period_end::text as period_end,
      period_type,
      strategy,
      total_trades,
      winning_trades,
      losing_trades,
      net_pnl_cents,
      win_rate,
      avg_win_cents,
      avg_loss_cents
    from deepstack_performance_metrics
    ${where}
    order by period_start desc
    limit $${params.length}
    `,
    params
  );
  return rows;
}

// ============================================================================
// BOT COMMANDS (Control Plane)
// ============================================================================

export async function createCommand(command: string, params: Record<string, unknown> = {}): Promise<BotCommand> {
  const commandId = crypto.randomUUID();
  const secret = getCommandHmacSecret();
  const signed = buildSignedCommandParams({
    commandId,
    command,
    params,
    secret,
    expiresInSeconds: 60,
  });

  const { rows } = await query<BotCommand>(
    `
    insert into deepstack_bot_commands (id, command, params, created_by)
    values ($1::uuid, $2, $3::jsonb, 'dashboard')
    returning
      id::text as id,
      command,
      params,
      status,
      result,
      created_at::text,
      executed_at::text as executed_at,
      created_by
    `,
    [commandId, command, JSON.stringify(signed.params)]
  );

  return rows[0]!;
}

export async function getRecentCommands(limit: number = 20): Promise<BotCommand[]> {
  const { rows } = await query<BotCommand>(
    `
    select
      id::text as id,
      command,
      params,
      status,
      result,
      created_at::text,
      executed_at::text as executed_at,
      created_by
    from deepstack_bot_commands
    order by created_at desc
    limit $1
    `,
    [limit]
  );
  return rows;
}

// ============================================================================
// BOT CONFIG (Control Plane)
// ============================================================================

export async function getBotConfig(): Promise<BotConfig | null> {
  const { rows } = await query<BotConfig>(
    `
    select
      id,
      mode,
      poll_interval_seconds,
      max_position_size_cents,
      daily_loss_limit_cents,
      kelly_fraction,
      strategies,
      profile,
      use_grok,
      last_heartbeat::text as last_heartbeat,
      updated_at::text as updated_at
    from deepstack_bot_config
    where id = 1
    limit 1
    `
  );
  return rows[0] || null;
}

export async function updateBotConfig(updates: Partial<BotConfig>): Promise<BotConfig | null> {
  const allowed = new Set([
    'mode',
    'poll_interval_seconds',
    'max_position_size_cents',
    'daily_loss_limit_cents',
    'kelly_fraction',
    'profile',
    'use_grok',
  ]);
  const keys = Object.keys(updates).filter((k) => allowed.has(k));
  if (keys.length === 0) return null;

  const setClauses: string[] = [];
  const params: unknown[] = [];
  keys.forEach((k, idx) => {
    setClauses.push(`${k} = $${idx + 1}`);
    // @ts-expect-error dynamic index
    params.push(updates[k] ?? null);
  });

  const { rows } = await query<BotConfig>(
    `
    update deepstack_bot_config
    set ${setClauses.join(', ')}
    where id = 1
    returning
      id,
      mode,
      poll_interval_seconds,
      max_position_size_cents,
      daily_loss_limit_cents,
      kelly_fraction,
      strategies,
      profile,
      use_grok,
      last_heartbeat::text as last_heartbeat,
      updated_at::text as updated_at
    `,
    params
  );
  return rows[0] || null;
}

