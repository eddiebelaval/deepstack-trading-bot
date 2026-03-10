import { NextRequest, NextResponse } from 'next/server';
import { withDb } from '@/lib/sqlite';

export const dynamic = 'force-dynamic';

// ---------------------------------------------------------------------------
// GET /api/analytics?view=equity|daily_pnl|strategy_perf|regime_timeline|win_rate|fitness_heatmap
// ---------------------------------------------------------------------------

const VALID_VIEWS = new Set([
  'equity', 'daily_pnl', 'strategy_perf', 'regime_timeline',
  'win_rate', 'fitness_heatmap', 'trade_scatter', 'market_state', 'governance',
]);

export async function GET(request: NextRequest) {
  const view = request.nextUrl.searchParams.get('view') || 'equity';
  const rawDays = parseInt(request.nextUrl.searchParams.get('days') || '30', 10);
  const days = Math.min(isNaN(rawDays) ? 30 : rawDays, 365);

  if (!VALID_VIEWS.has(view)) {
    return NextResponse.json({ error: 'Unknown view' }, { status: 400 });
  }

  try {
    const data = withDb((db) => {
      switch (view) {
        case 'equity':
          return db.prepare(`
            SELECT date, ending_balance_cents, starting_balance_cents, net_pnl_cents
            FROM daily_summary
            WHERE date >= date('now', '-' || ? || ' days')
            ORDER BY date ASC
          `).all(days);

        case 'daily_pnl':
          return db.prepare(`
            SELECT date, net_pnl_cents, total_trades, winning_trades, losing_trades,
                   largest_win_cents, largest_loss_cents
            FROM daily_summary
            WHERE date >= date('now', '-' || ? || ' days')
            ORDER BY date ASC
          `).all(days);

        case 'strategy_perf':
          return db.prepare(`
            SELECT strategy,
                   count(*) as total_trades,
                   sum(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as wins,
                   sum(CASE WHEN pnl_cents < 0 THEN 1 ELSE 0 END) as losses,
                   sum(CASE WHEN pnl_cents = 0 THEN 1 ELSE 0 END) as breakeven,
                   sum(pnl_cents) as total_pnl_cents,
                   avg(pnl_cents) as avg_pnl_cents,
                   max(pnl_cents) as best_trade_cents,
                   min(pnl_cents) as worst_trade_cents,
                   ROUND(sum(CASE WHEN pnl_cents > 0 THEN 1.0 ELSE 0 END) / count(*) * 100, 1) as win_rate
            FROM trades
            WHERE status = 'closed' AND pnl_cents IS NOT NULL
            GROUP BY strategy
            ORDER BY total_pnl_cents DESC
          `).all();

        case 'regime_timeline': {
          const totalRows = db.prepare(`
            SELECT count(*) as cnt FROM regime_history
            WHERE timestamp >= datetime('now', '-' || ? || ' days')
          `).get(days) as { cnt: number };

          const sampleRate = Math.max(1, Math.floor(totalRows.cnt / 500));
          return db.prepare(`
            SELECT id, regime, confidence, timestamp, volatility, trend_strength, source
            FROM regime_history
            WHERE timestamp >= datetime('now', '-' || ? || ' days')
              AND id % ? = 0
            ORDER BY timestamp ASC
          `).all(days, sampleRate);
        }

        case 'win_rate':
          return db.prepare(`
            SELECT
              t.id,
              t.updated_at,
              t.strategy,
              t.pnl_cents,
              SUM(CASE WHEN t2.pnl_cents > 0 THEN 1 ELSE 0 END) as cumulative_wins,
              COUNT(t2.id) as cumulative_trades,
              ROUND(SUM(CASE WHEN t2.pnl_cents > 0 THEN 1.0 ELSE 0 END) / COUNT(t2.id) * 100, 1) as rolling_win_rate,
              SUM(t2.pnl_cents) as cumulative_pnl_cents
            FROM trades t
            JOIN trades t2 ON t2.updated_at <= t.updated_at AND t2.status = 'closed' AND t2.pnl_cents IS NOT NULL
            WHERE t.status = 'closed' AND t.pnl_cents IS NOT NULL
            GROUP BY t.id
            ORDER BY t.updated_at ASC
          `).all();

        case 'fitness_heatmap':
          return db.prepare(`
            SELECT strategy_name, regime, fitness_score, trade_count, total_pnl_cents
            FROM strategy_regime_fitness
            WHERE trade_count > 0
            ORDER BY strategy_name, regime
          `).all();

        case 'trade_scatter':
          return db.prepare(`
            SELECT id, created_at, updated_at, market_ticker, strategy, side,
                   entry_price_cents, exit_price_cents, pnl_cents, contracts, is_paper
            FROM trades
            WHERE status = 'closed' AND pnl_cents IS NOT NULL
            ORDER BY updated_at ASC
          `).all();

        case 'market_state':
          return db.prepare(`
            SELECT r.source, r.regime, r.confidence, r.volatility,
                   r.trend_strength, r.mean_reversion_score, r.volume_ratio,
                   r.num_markets_sampled, r.timestamp
            FROM regime_history r
            INNER JOIN (
              SELECT source, MAX(id) as max_id FROM regime_history GROUP BY source
            ) latest ON r.id = latest.max_id
            ORDER BY r.source
          `).all();

        case 'governance':
          return db.prepare(`
            SELECT
              strftime('%Y-%m-%d %H:00', timestamp) as hour,
              regime,
              action,
              count(*) as decision_count,
              avg(regime_confidence) as avg_confidence
            FROM governance_decisions
            WHERE timestamp >= datetime('now', '-' || ? || ' days')
            GROUP BY hour, regime, action
            ORDER BY hour ASC
          `).all(days);

        default:
          return [];
      }
    });

    return NextResponse.json(
      { view, data: data ?? [] },
      { headers: { 'Cache-Control': 'private, max-age=15' } },
    );
  } catch (error) {
    console.error(`Analytics error (${view}):`, error);
    return NextResponse.json({ error: 'Analytics query failed', data: [] }, { status: 500 });
  }
}
