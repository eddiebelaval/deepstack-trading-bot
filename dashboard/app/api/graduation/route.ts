import { NextResponse } from 'next/server';
import { withDb } from '@/lib/sqlite';

export const dynamic = 'force-dynamic';

interface GateConfig {
  label: string;
  platform: string;
  strategies: string[];
  thresholds: {
    min_trades: number;
    min_win_rate: number;
    max_drawdown_pct: number;
    min_profitable_days?: number;
    min_avg_pnl_cents?: number;
  };
}

const GATES: GateConfig[] = [
  {
    label: 'KALSHI',
    platform: 'Prediction Markets',
    strategies: [
      'calibration_edge', 'high_probability_bonds', 'momentum', 'mean_reversion',
      'combinatorial_arbitrage', 'cross_platform_arbitrage', 'weather_aggregation',
      'news_sentiment_fade', 'correlated_event_arbitrage', 'domain_specialization',
      'crypto_intraday', 'bear_macro', 'settlement_betting',
    ],
    thresholds: { min_trades: 50, min_win_rate: 0.45, max_drawdown_pct: 15.0 },
  },
  {
    label: 'STOCKS',
    platform: 'IBKR Equities',
    strategies: ['stock_momentum', 'crisis_alpha'],
    thresholds: { min_trades: 30, min_win_rate: 0.50, max_drawdown_pct: 10.0, min_profitable_days: 5, min_avg_pnl_cents: 50 },
  },
  {
    label: 'FUTURES',
    platform: 'Micro Futures',
    strategies: ['futures_trend'],
    thresholds: { min_trades: 20, min_win_rate: 0.45, max_drawdown_pct: 8.0, min_profitable_days: 3, min_avg_pnl_cents: 100 },
  },
  {
    label: 'OPTIONS',
    platform: 'Sold Puts / Bought Calls',
    strategies: ['options_income', 'options_directional'],
    thresholds: { min_trades: 15, min_win_rate: 0.60, max_drawdown_pct: 12.0, min_profitable_days: 3, min_avg_pnl_cents: 75 },
  },
];

interface TradeRow {
  id: number;
  strategy: string;
  pnl_cents: number;
  updated_at: string;
  market_ticker: string;
  is_paper: number;
}

interface DailyPnl {
  day: string;
  pnl: number;
  trades: number;
}

interface GateResult {
  label: string;
  platform: string;
  thresholds: GateConfig['thresholds'];
  metrics: {
    total_trades: number;
    wins: number;
    losses: number;
    breakeven: number;
    win_rate: number;
    total_pnl_cents: number;
    avg_pnl_cents: number;
    best_trade_cents: number;
    worst_trade_cents: number;
    best_trade_ticker: string;
    worst_trade_ticker: string;
    max_drawdown_pct: number;
    profitable_days: number;
    total_days: number;
    current_streak: number;       // positive = win streak, negative = loss streak
    longest_win_streak: number;
    longest_loss_streak: number;
    daily_pnl: DailyPnl[];       // for sparkline
    strategies_active: number;
    strategies_total: number;
    regime_breakdown: { regime: string; trades: number; pnl: number }[];
  };
  gate_checks: {
    name: string;
    passed: boolean;
    current: number;
    target: number;
    format: 'number' | 'percent' | 'cents' | 'pct' | 'days';
    invert?: boolean;
  }[];
}

export async function GET() {
  try {
    const dbResults = withDb((db) => GATES.map((gate) => {
      // Build placeholder list for SQL IN clause
      const placeholders = gate.strategies.map(() => '?').join(',');

      // Get all closed paper trades for this gate's strategies
      const trades = db.prepare(`
        SELECT id, strategy, pnl_cents, updated_at, market_ticker, is_paper
        FROM trades
        WHERE status = 'closed'
          AND pnl_cents IS NOT NULL
          AND strategy IN (${placeholders})
        ORDER BY updated_at ASC
      `).all(...gate.strategies) as TradeRow[];

      if (trades.length === 0) {
        return {
          label: gate.label,
          platform: gate.platform,
          thresholds: gate.thresholds,
          metrics: {
            total_trades: 0, wins: 0, losses: 0, breakeven: 0,
            win_rate: 0, total_pnl_cents: 0, avg_pnl_cents: 0,
            best_trade_cents: 0, worst_trade_cents: 0,
            best_trade_ticker: '', worst_trade_ticker: '',
            max_drawdown_pct: 0, profitable_days: 0, total_days: 0,
            current_streak: 0, longest_win_streak: 0, longest_loss_streak: 0,
            daily_pnl: [], strategies_active: 0,
            strategies_total: gate.strategies.length,
            regime_breakdown: [],
          },
          gate_checks: buildGateChecks(gate, 0, 0, 0, 0, 0),
        };
      }

      const wins = trades.filter((t) => t.pnl_cents > 0);
      const losses = trades.filter((t) => t.pnl_cents < 0);
      const breakeven = trades.filter((t) => t.pnl_cents === 0);
      const totalPnl = trades.reduce((s, t) => s + t.pnl_cents, 0);
      const winRate = trades.length > 0 ? wins.length / trades.length : 0;
      const avgPnl = trades.length > 0 ? totalPnl / trades.length : 0;

      // Best / worst trades
      const sorted = [...trades].sort((a, b) => b.pnl_cents - a.pnl_cents);
      const best = sorted[0];
      const worst = sorted[sorted.length - 1];

      // Max drawdown (peak-to-trough)
      let peak = 0;
      let maxDd = 0;
      let cumulative = 0;
      for (const t of trades) {
        cumulative += t.pnl_cents;
        if (cumulative > peak) peak = cumulative;
        const dd = peak - cumulative;
        if (dd > maxDd) maxDd = dd;
      }
      // Express as percentage of peak (or starting balance proxy)
      const ddPct = peak > 0 ? (maxDd / peak) * 100 : 0;

      // Daily P&L aggregation
      const dailyMap = new Map<string, { pnl: number; trades: number }>();
      for (const t of trades) {
        const day = t.updated_at.split('T')[0];
        const entry = dailyMap.get(day) ?? { pnl: 0, trades: 0 };
        entry.pnl += t.pnl_cents;
        entry.trades += 1;
        dailyMap.set(day, entry);
      }
      const dailyPnl: DailyPnl[] = Array.from(dailyMap.entries())
        .map(([day, d]) => ({ day, pnl: d.pnl, trades: d.trades }))
        .sort((a, b) => a.day.localeCompare(b.day));
      const profitableDays = dailyPnl.filter((d) => d.pnl > 0).length;

      // Streaks
      let currentStreak = 0;
      let longestWin = 0;
      let longestLoss = 0;
      let winRun = 0;
      let lossRun = 0;
      for (const t of trades) {
        if (t.pnl_cents > 0) {
          winRun++;
          lossRun = 0;
          if (winRun > longestWin) longestWin = winRun;
        } else if (t.pnl_cents < 0) {
          lossRun++;
          winRun = 0;
          if (lossRun > longestLoss) longestLoss = lossRun;
        }
      }
      // Current streak from last trade
      const lastTrades = [...trades].reverse();
      if (lastTrades.length > 0) {
        const lastSign = lastTrades[0].pnl_cents > 0 ? 1 : -1;
        currentStreak = 0;
        for (const t of lastTrades) {
          const sign = t.pnl_cents > 0 ? 1 : t.pnl_cents < 0 ? -1 : 0;
          if (sign === lastSign) currentStreak++;
          else break;
        }
        if (lastSign < 0) currentStreak = -currentStreak;
      }

      // Active strategies (ones with at least 1 trade)
      const activeStrategies = new Set(trades.map((t) => t.strategy));

      // Regime breakdown — join with regime at time of trade
      const regimeBreakdown = db.prepare(`
        SELECT rh.regime, COUNT(*) as trades, SUM(t.pnl_cents) as pnl
        FROM trades t
        LEFT JOIN regime_history rh ON rh.id = (
          SELECT id FROM regime_history
          WHERE timestamp <= t.updated_at
          ORDER BY timestamp DESC LIMIT 1
        )
        WHERE t.status = 'closed'
          AND t.pnl_cents IS NOT NULL
          AND t.strategy IN (${placeholders})
        GROUP BY rh.regime
        ORDER BY trades DESC
      `).all(...gate.strategies) as { regime: string; trades: number; pnl: number }[];

      return {
        label: gate.label,
        platform: gate.platform,
        thresholds: gate.thresholds,
        metrics: {
          total_trades: trades.length,
          wins: wins.length,
          losses: losses.length,
          breakeven: breakeven.length,
          win_rate: winRate,
          total_pnl_cents: totalPnl,
          avg_pnl_cents: avgPnl,
          best_trade_cents: best.pnl_cents,
          worst_trade_cents: worst.pnl_cents,
          best_trade_ticker: best.market_ticker,
          worst_trade_ticker: worst.market_ticker,
          max_drawdown_pct: ddPct,
          profitable_days: profitableDays,
          total_days: dailyPnl.length,
          current_streak: currentStreak,
          longest_win_streak: longestWin,
          longest_loss_streak: longestLoss,
          daily_pnl: dailyPnl,
          strategies_active: activeStrategies.size,
          strategies_total: gate.strategies.length,
          regime_breakdown: regimeBreakdown,
        },
        gate_checks: buildGateChecks(gate, trades.length, winRate, ddPct, profitableDays, avgPnl),
      };
    }));

    return NextResponse.json(
      { gates: dbResults ?? [] },
      { headers: { 'Cache-Control': 'private, max-age=15' } },
    );
  } catch (error) {
    console.error('Graduation API error:', error);
    return NextResponse.json({ gates: [] }, { status: 500 });
  }
}

function buildGateChecks(
  gate: GateConfig,
  trades: number,
  winRate: number,
  drawdownPct: number,
  profitableDays: number,
  avgPnl: number,
) {
  const checks: GateResult['gate_checks'] = [
    {
      name: 'TRADES',
      passed: trades >= gate.thresholds.min_trades,
      current: trades,
      target: gate.thresholds.min_trades,
      format: 'number',
    },
    {
      name: 'WIN RATE',
      passed: winRate >= gate.thresholds.min_win_rate,
      current: winRate,
      target: gate.thresholds.min_win_rate,
      format: 'percent',
    },
    {
      name: 'MAX DRAWDOWN',
      passed: drawdownPct <= gate.thresholds.max_drawdown_pct,
      current: drawdownPct,
      target: gate.thresholds.max_drawdown_pct,
      format: 'pct',
      invert: true,
    },
  ];

  if (gate.thresholds.min_profitable_days) {
    checks.push({
      name: 'PROFITABLE DAYS',
      passed: profitableDays >= gate.thresholds.min_profitable_days,
      current: profitableDays,
      target: gate.thresholds.min_profitable_days,
      format: 'number',
    });
  }
  if (gate.thresholds.min_avg_pnl_cents) {
    checks.push({
      name: 'AVG P&L',
      passed: avgPnl >= gate.thresholds.min_avg_pnl_cents,
      current: avgPnl,
      target: gate.thresholds.min_avg_pnl_cents,
      format: 'cents',
    });
  }

  return checks;
}
