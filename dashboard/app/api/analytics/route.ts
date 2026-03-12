import { NextRequest, NextResponse } from 'next/server';
import { restGet } from '@/lib/postgres';
import { withDb } from '@/lib/sqlite';
import type { StrategyFitnessRow, DecisionAuditCycle } from '@/lib/weather-types';

export const dynamic = 'force-dynamic';

// ---------------------------------------------------------------------------
// GET /api/analytics?view=...
// Tries Supabase first (works on Vercel). Falls back to local SQLite.
// ---------------------------------------------------------------------------

const VALID_VIEWS = new Set([
  'equity', 'daily_pnl', 'strategy_perf', 'regime_timeline',
  'win_rate', 'fitness_heatmap', 'trade_scatter', 'market_state', 'governance',
  'decision_audit',
]);

interface TradeRow {
  id: number;
  strategy: string;
  status: string;
  pnl_cents: number;
  updated_at: string;
  created_at: string;
  market_ticker: string;
  side: string;
  contracts: number;
  entry_price_cents: number;
  exit_price_cents: number | null;
  is_paper: boolean;
  session_date: string | null;
}

interface RegimeRow {
  id: number;
  regime: string;
  confidence: number;
  volatility: number;
  trend_strength: number;
  mean_reversion_score: number;
  volume_ratio: number;
  num_markets_sampled: number;
  timestamp: string;
  source?: string;
}

interface GovernanceDecisionRow {
  id: number;
  timestamp: string;
  regime: string;
  regime_confidence: number | null;
  action: string;
  strategy_name: string | null;
  reason: string | null;
  mode: string | null;
}


const DECISION_AUDIT_LIMIT = 18;
const DECISION_AUDIT_WINDOW_HOURS = 3;
const REGIME_MATCH_WINDOW_MS = 5 * 60 * 1000;

function normalizeRegimeSource(source?: string | null): string {
  if (!source) return 'prediction_market';
  if (source === 'prediction') return 'prediction_market';
  return source;
}

async function restGetOptionalSource<T extends { source?: string }>(
  table: string,
  withSourceParams: string,
  withoutSourceParams: string,
  defaultSource = 'prediction_market',
): Promise<T[]> {
  try {
    const rows = await restGet<T>(table, withSourceParams);
    return rows.map((row) => ({ ...row, source: normalizeRegimeSource(row.source ?? defaultSource) }));
  } catch {
    const rows = await restGet<T>(table, withoutSourceParams);
    return rows.map((row) => ({ ...row, source: defaultSource }));
  }
}

function buildDecisionAudit(
  decisions: GovernanceDecisionRow[],
  regimes: RegimeRow[],
  fitness: StrategyFitnessRow[],
  trades: TradeRow[],
): DecisionAuditCycle[] {
  const grouped = new Map<string, GovernanceDecisionRow[]>();
  for (const decision of decisions) {
    const key = decision.timestamp;
    const bucket = grouped.get(key) ?? [];
    bucket.push(decision);
    grouped.set(key, bucket);
  }

  const timestamps = Array.from(grouped.keys())
    .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())
    .slice(0, DECISION_AUDIT_LIMIT);

  const normalizedRegimes = regimes.map((row) => ({
    ...row,
    source: normalizeRegimeSource(row.source),
  }));

  const nearestReading = (source: string, timestamp: string): RegimeRow | null => {
    const target = new Date(timestamp).getTime();
    let best: RegimeRow | null = null;
    let bestDelta = Number.POSITIVE_INFINITY;

    for (const row of normalizedRegimes) {
      if (normalizeRegimeSource(row.source) !== source) continue;
      const delta = Math.abs(new Date(row.timestamp).getTime() - target);
      if (delta <= REGIME_MATCH_WINDOW_MS && delta < bestDelta) {
        best = row;
        bestDelta = delta;
      }
    }

    return best;
  };

  return timestamps.map((timestamp) => {
    const bucket = grouped.get(timestamp) ?? [];
    const predictionMarket = nearestReading('prediction_market', timestamp);
    const stock = nearestReading('stock', timestamp);
    const decisionRegime = bucket[0]?.regime ?? predictionMarket?.regime ?? stock?.regime ?? null;
    const enable = bucket
      .filter((row) => row.action === 'enable' && row.strategy_name)
      .map((row) => row.strategy_name as string);
    const disable = bucket
      .filter((row) => row.action === 'disable' && row.strategy_name)
      .map((row) => row.strategy_name as string);
    const reasons = Array.from(
      new Set(
        bucket
          .map((row) => row.reason?.trim())
          .filter((reason): reason is string => Boolean(reason))
          .slice(0, 4),
      ),
    );

    let agreement: DecisionAuditCycle['translation']['agreement'] = 'unknown';
    let steeringSource: DecisionAuditCycle['translation']['steering_source'] = 'unknown';
    let confidenceGap: number | null = null;

    if (predictionMarket && stock) {
      confidenceGap = Math.round(Math.abs(predictionMarket.confidence - stock.confidence) * 1000) / 1000;
      if (predictionMarket.regime === stock.regime) {
        agreement = 'agree';
        steeringSource = 'both';
      } else if (decisionRegime === predictionMarket.regime) {
        agreement = 'diverge';
        steeringSource = 'prediction_market';
      } else if (decisionRegime === stock.regime) {
        agreement = 'diverge';
        steeringSource = 'stock';
      } else {
        agreement = 'partial';
      }
    } else if (predictionMarket || stock) {
      agreement = 'partial';
      steeringSource = predictionMarket ? 'prediction_market' : 'stock';
    }

    const touchedStrategies = new Set([...enable, ...disable]);
    const start = new Date(timestamp).getTime();
    const end = start + DECISION_AUDIT_WINDOW_HOURS * 60 * 60 * 1000;
    const outcomeTrades = trades.filter((trade) => {
      if (trade.pnl_cents == null || trade.status !== 'closed' || !trade.updated_at) return false;
      if (touchedStrategies.size > 0 && !touchedStrategies.has(trade.strategy)) return false;
      const updatedAt = new Date(trade.updated_at).getTime();
      return updatedAt >= start && updatedAt <= end;
    });

    const topFitness = fitness
      .filter((row) => row.regime === decisionRegime)
      .sort((a, b) => b.fitness_score - a.fitness_score)
      .slice(0, 4);

    return {
      timestamp,
      observed: {
        prediction_market: predictionMarket,
        stock,
      },
      translation: {
        effective_regime: decisionRegime,
        agreement,
        steering_source: steeringSource,
        confidence_gap: confidenceGap,
      },
      decisions: {
        regime: decisionRegime ?? 'unknown',
        confidence: bucket[0]?.regime_confidence ?? predictionMarket?.confidence ?? stock?.confidence ?? null,
        mode: bucket[0]?.mode ?? null,
        enable,
        disable,
        reasons,
      },
      context: {
        top_fitness: topFitness,
      },
      outcome: {
        trade_count: outcomeTrades.length,
        net_pnl_cents: outcomeTrades.reduce((sum, trade) => sum + (trade.pnl_cents ?? 0), 0),
        window_hours: DECISION_AUDIT_WINDOW_HOURS,
      },
    };
  });
}

// ---------------------------------------------------------------------------
// Supabase-backed analytics (works on Vercel)
// ---------------------------------------------------------------------------

async function supabaseDailyPnl(days: number) {
  const trades = await restGet<TradeRow>(
    'deepstack_trades',
    `status=eq.closed&pnl_cents=not.is.null&select=pnl_cents,updated_at,session_date&order=updated_at.asc`,
  );
  if (trades.length === 0) return [];

  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);

  const dailyMap = new Map<string, {
    net_pnl_cents: number; total_trades: number;
    winning_trades: number; losing_trades: number;
    largest_win_cents: number; largest_loss_cents: number;
  }>();

  for (const t of trades) {
    const day = t.session_date || t.updated_at.split('T')[0];
    if (new Date(day) < cutoff) continue;

    const entry = dailyMap.get(day) ?? {
      net_pnl_cents: 0, total_trades: 0,
      winning_trades: 0, losing_trades: 0,
      largest_win_cents: 0, largest_loss_cents: 0,
    };
    entry.net_pnl_cents += t.pnl_cents;
    entry.total_trades += 1;
    if (t.pnl_cents > 0) {
      entry.winning_trades += 1;
      entry.largest_win_cents = Math.max(entry.largest_win_cents, t.pnl_cents);
    } else if (t.pnl_cents < 0) {
      entry.losing_trades += 1;
      entry.largest_loss_cents = Math.min(entry.largest_loss_cents, t.pnl_cents);
    }
    dailyMap.set(day, entry);
  }

  return Array.from(dailyMap.entries())
    .map(([date, d]) => ({ date, ...d }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

async function supabaseWinRate() {
  const trades = await restGet<TradeRow>(
    'deepstack_trades',
    `status=eq.closed&pnl_cents=not.is.null&select=id,updated_at,strategy,pnl_cents&order=updated_at.asc`,
  );
  if (trades.length === 0) return [];

  let cumulativeWins = 0;
  let cumulativePnl = 0;

  return trades.map((t, i) => {
    if (t.pnl_cents > 0) cumulativeWins++;
    cumulativePnl += t.pnl_cents;
    return {
      id: t.id,
      updated_at: t.updated_at,
      strategy: t.strategy,
      pnl_cents: t.pnl_cents,
      cumulative_wins: cumulativeWins,
      cumulative_trades: i + 1,
      rolling_win_rate: Math.round((cumulativeWins / (i + 1)) * 1000) / 10,
      cumulative_pnl_cents: cumulativePnl,
    };
  });
}

async function supabaseStrategyPerf() {
  const trades = await restGet<TradeRow>(
    'deepstack_trades',
    `status=eq.closed&pnl_cents=not.is.null&select=strategy,pnl_cents&order=updated_at.asc`,
  );
  if (trades.length === 0) return [];

  const byStrategy = new Map<string, {
    total_trades: number; wins: number; losses: number; breakeven: number;
    total_pnl_cents: number; best_trade_cents: number; worst_trade_cents: number;
    pnl_values: number[];
  }>();

  for (const t of trades) {
    const entry = byStrategy.get(t.strategy) ?? {
      total_trades: 0, wins: 0, losses: 0, breakeven: 0,
      total_pnl_cents: 0, best_trade_cents: -Infinity, worst_trade_cents: Infinity,
      pnl_values: [],
    };
    entry.total_trades++;
    entry.total_pnl_cents += t.pnl_cents;
    entry.pnl_values.push(t.pnl_cents);
    entry.best_trade_cents = Math.max(entry.best_trade_cents, t.pnl_cents);
    entry.worst_trade_cents = Math.min(entry.worst_trade_cents, t.pnl_cents);
    if (t.pnl_cents > 0) entry.wins++;
    else if (t.pnl_cents < 0) entry.losses++;
    else entry.breakeven++;
    byStrategy.set(t.strategy, entry);
  }

  return Array.from(byStrategy.entries())
    .map(([strategy, s]) => ({
      strategy,
      total_trades: s.total_trades,
      wins: s.wins,
      losses: s.losses,
      breakeven: s.breakeven,
      total_pnl_cents: s.total_pnl_cents,
      avg_pnl_cents: Math.round(s.total_pnl_cents / s.total_trades),
      best_trade_cents: s.best_trade_cents === -Infinity ? 0 : s.best_trade_cents,
      worst_trade_cents: s.worst_trade_cents === Infinity ? 0 : s.worst_trade_cents,
      win_rate: Math.round((s.wins / s.total_trades) * 1000) / 10,
    }))
    .sort((a, b) => b.total_pnl_cents - a.total_pnl_cents);
}

async function supabaseTradeScatter() {
  return restGet<TradeRow>(
    'deepstack_trades',
    `status=eq.closed&pnl_cents=not.is.null&select=id,created_at,updated_at,market_ticker,strategy,side,entry_price_cents,exit_price_cents,pnl_cents,contracts,is_paper&order=updated_at.asc`,
  );
}

async function supabaseFitnessHeatmap() {
  // Try the fitness table first
  const rows = await restGet<StrategyFitnessRow>(
    'deepstack_strategy_regime_fitness',
    `trade_count=gt.0&select=strategy_name,regime,fitness_score,trade_count,total_pnl_cents,last_updated&order=strategy_name,regime`,
  ).catch(() => []);

  if (rows.length > 0) return rows;

  // Fallback: compute from trades + regime data
  const [trades, regimes] = await Promise.all([
    restGet<TradeRow>(
      'deepstack_trades',
      `status=eq.closed&pnl_cents=not.is.null&select=strategy,pnl_cents,updated_at&order=updated_at.asc`,
    ).catch(() => []),
    restGetOptionalSource<RegimeRow>(
      'deepstack_regime_history',
      `select=id,source,regime,timestamp&order=timestamp.asc&limit=5000`,
      `select=id,regime,timestamp&order=timestamp.asc&limit=5000`,
    ).catch(() => []),
  ]);

  if (trades.length === 0 || regimes.length === 0) return [];

  // Match each trade to the nearest regime snapshot
  const fitnessMap = new Map<string, { wins: number; total: number; pnl: number }>();
  for (const trade of trades) {
    const tradeTime = new Date(trade.updated_at).getTime();
    let nearestRegime = regimes[0]?.regime ?? 'unknown';
    let minDelta = Infinity;
    for (const r of regimes) {
      const delta = Math.abs(new Date(r.timestamp).getTime() - tradeTime);
      if (delta < minDelta) {
        minDelta = delta;
        nearestRegime = r.regime;
      }
    }

    const key = `${trade.strategy}|${nearestRegime}`;
    const entry = fitnessMap.get(key) ?? { wins: 0, total: 0, pnl: 0 };
    entry.total++;
    entry.pnl += trade.pnl_cents;
    if (trade.pnl_cents > 0) entry.wins++;
    fitnessMap.set(key, entry);
  }

  return Array.from(fitnessMap.entries())
    .filter(([, v]) => v.total > 0)
    .map(([key, v]) => {
      const [strategy_name, regime] = key.split('|');
      return {
        strategy_name,
        regime,
        fitness_score: Math.round((v.wins / v.total) * 100) / 100,
        trade_count: v.total,
        total_pnl_cents: v.pnl,
      };
    });
}

async function supabaseMarketState() {
  const rows = await restGetOptionalSource<RegimeRow>(
    'deepstack_regime_history',
    `select=id,source,regime,confidence,volatility,trend_strength,mean_reversion_score,volume_ratio,num_markets_sampled,timestamp&order=id.desc&limit=20`,
    `select=id,regime,confidence,volatility,trend_strength,mean_reversion_score,volume_ratio,num_markets_sampled,timestamp&order=id.desc&limit=20`,
  );
  const seen = new Set<string>();
  return rows.filter((row) => {
    const source = normalizeRegimeSource(row.source);
    if (seen.has(source)) return false;
    seen.add(source);
    return true;
  });
}

async function supabaseRegimeTimeline(days: number) {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  return restGetOptionalSource<RegimeRow>(
    'deepstack_regime_history',
    `timestamp=gte.${cutoff.toISOString()}&select=id,source,regime,confidence,timestamp,volatility,trend_strength,mean_reversion_score,volume_ratio,num_markets_sampled&order=timestamp.asc&limit=500`,
    `timestamp=gte.${cutoff.toISOString()}&select=id,regime,confidence,timestamp,volatility,trend_strength,mean_reversion_score,volume_ratio,num_markets_sampled&order=timestamp.asc&limit=500`,
  );
}

async function supabaseEquity(days: number) {
  // Compute equity curve from trades
  const trades = await restGet<TradeRow>(
    'deepstack_trades',
    `status=eq.closed&pnl_cents=not.is.null&select=pnl_cents,updated_at,session_date&order=updated_at.asc`,
  );
  if (trades.length === 0) return [];

  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);

  const dailyMap = new Map<string, number>();
  for (const t of trades) {
    const day = t.session_date || t.updated_at.split('T')[0];
    if (new Date(day) < cutoff) continue;
    dailyMap.set(day, (dailyMap.get(day) ?? 0) + t.pnl_cents);
  }

  let cumulative = 0;
  return Array.from(dailyMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, net_pnl_cents]) => {
      const starting = cumulative;
      cumulative += net_pnl_cents;
      return { date, starting_balance_cents: starting, ending_balance_cents: cumulative, net_pnl_cents };
    });
}

async function supabaseDecisionAudit(days: number) {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);

  const [decisions, regimes, fitness, trades] = await Promise.all([
    restGet<GovernanceDecisionRow>(
      'deepstack_governance_decisions',
      `timestamp=gte.${cutoff.toISOString()}&select=id,timestamp,regime,regime_confidence,action,strategy_name,reason,mode&order=timestamp.desc&limit=500`,
    ).catch(() => []),
    restGetOptionalSource<RegimeRow>(
      'deepstack_regime_history',
      `timestamp=gte.${cutoff.toISOString()}&select=id,source,regime,confidence,timestamp,volatility,trend_strength,mean_reversion_score,volume_ratio,num_markets_sampled&order=timestamp.desc&limit=1000`,
      `timestamp=gte.${cutoff.toISOString()}&select=id,regime,confidence,timestamp,volatility,trend_strength,mean_reversion_score,volume_ratio,num_markets_sampled&order=timestamp.desc&limit=1000`,
    ).catch(() => []),
    restGet<StrategyFitnessRow>(
      'deepstack_strategy_regime_fitness',
      `select=strategy_name,regime,fitness_score,trade_count,total_pnl_cents,last_updated&order=fitness_score.desc&limit=500`,
    ).catch(() => []),
    restGet<TradeRow>(
      'deepstack_trades',
      `status=eq.closed&pnl_cents=not.is.null&updated_at=gte.${cutoff.toISOString()}&select=id,strategy,pnl_cents,updated_at,created_at,market_ticker,side,contracts,entry_price_cents,exit_price_cents,is_paper,session_date&order=updated_at.desc&limit=1000`,
    ).catch(() => []),
  ]);

  if (decisions.length === 0) return [];
  return buildDecisionAudit(decisions, regimes, fitness, trades);
}

// ---------------------------------------------------------------------------
// SQLite fallback (local dev only)
// ---------------------------------------------------------------------------

function sqliteAnalytics(view: string, days: number): unknown[] | null {
  return withDb((db) => {
    switch (view) {
      case 'equity':
        return db.prepare(`
          SELECT date, ending_balance_cents, starting_balance_cents, net_pnl_cents
          FROM daily_summary WHERE date >= date('now', '-' || ? || ' days') ORDER BY date ASC
        `).all(days);
      case 'daily_pnl':
        return db.prepare(`
          SELECT date, net_pnl_cents, total_trades, winning_trades, losing_trades,
                 largest_win_cents, largest_loss_cents
          FROM daily_summary WHERE date >= date('now', '-' || ? || ' days') ORDER BY date ASC
        `).all(days);
      case 'strategy_perf':
        return db.prepare(`
          SELECT strategy, count(*) as total_trades,
                 sum(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as wins,
                 sum(CASE WHEN pnl_cents < 0 THEN 1 ELSE 0 END) as losses,
                 sum(pnl_cents) as total_pnl_cents, avg(pnl_cents) as avg_pnl_cents,
                 ROUND(sum(CASE WHEN pnl_cents > 0 THEN 1.0 ELSE 0 END) / count(*) * 100, 1) as win_rate
          FROM trades WHERE status = 'closed' AND pnl_cents IS NOT NULL
          GROUP BY strategy ORDER BY total_pnl_cents DESC
        `).all();
      case 'regime_timeline': {
        const totalRows = db.prepare(`
          SELECT count(*) as cnt FROM regime_history WHERE timestamp >= datetime('now', '-' || ? || ' days')
        `).get(days) as { cnt: number };
        const sampleRate = Math.max(1, Math.floor(totalRows.cnt / 500));
        return db.prepare(`
          SELECT id, regime, confidence, timestamp, volatility, trend_strength, source
          FROM regime_history WHERE timestamp >= datetime('now', '-' || ? || ' days') AND id % ? = 0
          ORDER BY timestamp ASC
        `).all(days, sampleRate);
      }
      case 'win_rate':
        return db.prepare(`
          SELECT t.id, t.updated_at, t.strategy, t.pnl_cents,
                 SUM(CASE WHEN t2.pnl_cents > 0 THEN 1 ELSE 0 END) as cumulative_wins,
                 COUNT(t2.id) as cumulative_trades,
                 ROUND(SUM(CASE WHEN t2.pnl_cents > 0 THEN 1.0 ELSE 0 END) / COUNT(t2.id) * 100, 1) as rolling_win_rate,
                 SUM(t2.pnl_cents) as cumulative_pnl_cents
          FROM trades t JOIN trades t2 ON t2.updated_at <= t.updated_at AND t2.status = 'closed' AND t2.pnl_cents IS NOT NULL
          WHERE t.status = 'closed' AND t.pnl_cents IS NOT NULL GROUP BY t.id ORDER BY t.updated_at ASC
        `).all();
      case 'fitness_heatmap':
        return db.prepare(`
          SELECT strategy_name, regime, fitness_score, trade_count, total_pnl_cents
          FROM strategy_regime_fitness WHERE trade_count > 0 ORDER BY strategy_name, regime
        `).all();
      case 'market_state':
        return db.prepare(`
          SELECT r.source, r.regime, r.confidence, r.volatility,
                 r.trend_strength, r.mean_reversion_score, r.volume_ratio,
                 r.num_markets_sampled, r.timestamp
          FROM regime_history r INNER JOIN (
            SELECT source, MAX(id) as max_id FROM regime_history GROUP BY source
          ) latest ON r.id = latest.max_id ORDER BY r.source
        `).all();
      case 'governance':
        return db.prepare(`
          SELECT strftime('%Y-%m-%d %H:00', timestamp) as hour, regime, action,
                 count(*) as decision_count, avg(regime_confidence) as avg_confidence
          FROM governance_decisions WHERE timestamp >= datetime('now', '-' || ? || ' days')
          GROUP BY hour, regime, action ORDER BY hour ASC
        `).all(days);
      case 'decision_audit': {
        const decisions = db.prepare(`
          SELECT id, timestamp, regime, regime_confidence, action, strategy_name, reason, mode
          FROM governance_decisions
          WHERE timestamp >= datetime('now', '-' || ? || ' days')
          ORDER BY timestamp DESC, id DESC
          LIMIT 500
        `).all(days) as GovernanceDecisionRow[];
        const regimes = db.prepare(`
          SELECT id, source, regime, confidence, volatility, trend_strength,
                 mean_reversion_score, volume_ratio, num_markets_sampled, timestamp
          FROM regime_history
          WHERE timestamp >= datetime('now', '-' || ? || ' days')
          ORDER BY timestamp DESC, id DESC
          LIMIT 1000
        `).all(days) as RegimeRow[];
        const fitness = db.prepare(`
          SELECT strategy_name, regime, fitness_score, trade_count, total_pnl_cents, last_updated
          FROM strategy_regime_fitness
          WHERE trade_count > 0
          ORDER BY fitness_score DESC, trade_count DESC
        `).all() as StrategyFitnessRow[];
        const trades = db.prepare(`
          SELECT id, strategy, pnl_cents, updated_at, created_at, market_ticker, side,
                 contracts, entry_price_cents, exit_price_cents, is_paper, session_date, status
          FROM trades
          WHERE status = 'closed'
            AND pnl_cents IS NOT NULL
            AND updated_at >= datetime('now', '-' || ? || ' days')
          ORDER BY updated_at DESC, id DESC
          LIMIT 1000
        `).all(days) as TradeRow[];
        return buildDecisionAudit(decisions, regimes, fitness, trades);
      }
      default:
        return [];
    }
  });
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

export async function GET(request: NextRequest) {
  const view = request.nextUrl.searchParams.get('view') || 'equity';
  const rawDays = parseInt(request.nextUrl.searchParams.get('days') || '30', 10);
  const days = Math.min(isNaN(rawDays) ? 30 : rawDays, 365);

  if (!VALID_VIEWS.has(view)) {
    return NextResponse.json({ error: 'Unknown view' }, { status: 400 });
  }

  try {
    // Try Supabase first (works on Vercel)
    let data: unknown[] | null = null;

    switch (view) {
      case 'daily_pnl':
        data = await supabaseDailyPnl(days);
        break;
      case 'win_rate':
        data = await supabaseWinRate();
        break;
      case 'strategy_perf':
        data = await supabaseStrategyPerf();
        break;
      case 'trade_scatter':
        data = await supabaseTradeScatter();
        break;
      case 'fitness_heatmap':
        data = await supabaseFitnessHeatmap();
        break;
      case 'market_state':
        data = await supabaseMarketState();
        break;
      case 'regime_timeline':
        data = await supabaseRegimeTimeline(days);
        break;
      case 'equity':
        data = await supabaseEquity(days);
        break;
      case 'decision_audit':
        data = await supabaseDecisionAudit(days);
        break;
      default:
        // Views not yet migrated — try Supabase tables, fallback to SQLite
        data = null;
    }

    // Fallback to SQLite if Supabase returned empty and local DB exists
    if ((!data || data.length === 0)) {
      const sqliteData = sqliteAnalytics(view, days);
      if (sqliteData && sqliteData.length > 0) {
        data = sqliteData;
      }
    }

    return NextResponse.json(
      { view, data: data ?? [] },
      { headers: { 'Cache-Control': 'private, max-age=15' } },
    );
  } catch (error) {
    console.error(`Analytics error (${view}):`, error);
    return NextResponse.json({ error: 'Analytics query failed', data: [] }, { status: 500 });
  }
}
