import { NextRequest, NextResponse } from 'next/server';
import { restGet } from '@/lib/postgres';
import { withDb } from '@/lib/sqlite';

export const dynamic = 'force-dynamic';

// ---------------------------------------------------------------------------
// GET /api/analytics?view=...
// Tries Supabase first (works on Vercel). Falls back to local SQLite.
// ---------------------------------------------------------------------------

const VALID_VIEWS = new Set([
  'equity', 'daily_pnl', 'strategy_perf', 'regime_timeline',
  'win_rate', 'fitness_heatmap', 'trade_scatter', 'market_state', 'governance',
]);

interface TradeRow {
  id: number;
  strategy: string;
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

async function supabaseMarketState() {
  try {
    const rows = await restGet<RegimeRow>(
      'deepstack_regime_history',
      `select=regime,confidence,volatility,trend_strength,mean_reversion_score,volume_ratio,num_markets_sampled,timestamp&order=id.desc&limit=5`,
    );
    // Default source since column doesn't exist in Supabase yet
    return rows.map((r) => ({ ...r, source: r.source ?? 'prediction_market' }));
  } catch {
    return [];
  }
}

async function supabaseRegimeTimeline(days: number) {
  try {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    const rows = await restGet<RegimeRow>(
      'deepstack_regime_history',
      `timestamp=gte.${cutoff.toISOString()}&select=id,regime,confidence,timestamp,volatility,trend_strength&order=timestamp.asc&limit=500`,
    );
    return rows.map((r) => ({ ...r, source: r.source ?? 'prediction_market' }));
  } catch {
    return [];
  }
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
      case 'market_state':
        data = await supabaseMarketState();
        break;
      case 'regime_timeline':
        data = await supabaseRegimeTimeline(days);
        break;
      case 'equity':
        data = await supabaseEquity(days);
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
