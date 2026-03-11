import { NextResponse } from 'next/server';
import { restGet } from '@/lib/postgres';

export const dynamic = 'force-dynamic';

// ---------------------------------------------------------------------------
// Blending weights — backtest provides statistical confidence,
// paper trading validates execution reality
// ---------------------------------------------------------------------------

const BACKTEST_WEIGHT = 0.65;
const PAPER_WEIGHT = 0.35;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
  id: string;
  strategy: string;
  pnl_cents: number;
  updated_at: string;
  market_ticker: string;
}

interface StockTradeRow {
  id: string;
  ticker: string;
  action: string;
  qty: number;
  price_cents: number;
  strategy: string;
  pnl_cents: number | null;
  session_date: string | null;
  created_at: string;
}

interface BacktestRow {
  strategy: string;
  gate: string;
  total_trades: number;
  win_rate: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  profit_factor: number;
  avg_pnl_cents: number;
  total_pnl_cents: number;
  composite_score: number;
  data_source: string;
  time_window: string | null;
  created_at: string;
}

interface DailyPnl {
  day: string;
  pnl: number;
  trades: number;
}

interface BacktestConfidence {
  score: number;           // 0-100 composite from arena
  strategies_tested: number;
  total_bt_trades: number;
  avg_win_rate: number;
  avg_sharpe: number;
  avg_drawdown_pct: number;
  data_source: string;
  last_run: string;        // ISO timestamp
}

interface GateCheck {
  name: string;
  passed: boolean;
  current: number;
  target: number;
  format: 'number' | 'percent' | 'cents' | 'pct' | 'days';
  invert?: boolean;
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
    current_streak: number;
    longest_win_streak: number;
    longest_loss_streak: number;
    daily_pnl: DailyPnl[];
    strategies_active: number;
    strategies_total: number;
    regime_breakdown: { regime: string; trades: number; pnl: number }[];
  };
  gate_checks: GateCheck[];
  // Hybrid graduation fields
  paper_readiness: number;       // 0-1 (existing gate check pass ratio)
  backtest_confidence: BacktestConfidence | null;
  blended_readiness: number;     // 0-1 weighted blend
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function fetchClosedTrades(): Promise<TradeRow[]> {
  return restGet<TradeRow>(
    'deepstack_trades',
    'status=eq.closed&pnl_cents=not.is.null&select=id,strategy,pnl_cents,updated_at,market_ticker&order=updated_at.asc'
  );
}

async function fetchStockTrades(): Promise<TradeRow[]> {
  try {
    const rows = await restGet<StockTradeRow>(
      'deepstack_stock_trades',
      'pnl_cents=not.is.null&select=id,ticker,action,qty,price_cents,strategy,pnl_cents,session_date,created_at&order=created_at.asc'
    );
    // Normalize to TradeRow shape so computeGate works for both
    return rows.map((r) => ({
      id: r.id,
      strategy: r.strategy,
      pnl_cents: r.pnl_cents ?? 0,
      updated_at: r.created_at,
      market_ticker: r.ticker,
    }));
  } catch {
    // Table may not exist yet
    return [];
  }
}

async function fetchBacktestResults(): Promise<BacktestRow[]> {
  try {
    return await restGet<BacktestRow>(
      'deepstack_backtest_results',
      'select=strategy,gate,total_trades,win_rate,max_drawdown_pct,sharpe_ratio,profit_factor,avg_pnl_cents,total_pnl_cents,composite_score,data_source,time_window,created_at&order=created_at.desc'
    );
  } catch {
    // Table may not exist yet — graceful fallback
    return [];
  }
}

// ---------------------------------------------------------------------------
// Backtest confidence aggregation
// ---------------------------------------------------------------------------

function computeBacktestConfidence(
  gate: GateConfig,
  allBacktests: BacktestRow[],
): BacktestConfidence | null {
  // Get latest backtest result per strategy for this gate
  const gateResults = allBacktests.filter((r) => r.gate === gate.label);
  if (gateResults.length === 0) return null;

  // Deduplicate: keep only the latest result per strategy
  const latestByStrategy = new Map<string, BacktestRow>();
  for (const r of gateResults) {
    const existing = latestByStrategy.get(r.strategy);
    if (!existing || r.created_at > existing.created_at) {
      latestByStrategy.set(r.strategy, r);
    }
  }

  const results = Array.from(latestByStrategy.values());
  if (results.length === 0) return null;

  const totalBtTrades = results.reduce((s, r) => s + r.total_trades, 0);
  const avgWinRate = results.reduce((s, r) => s + r.win_rate, 0) / results.length;
  const avgSharpe = results.reduce((s, r) => s + r.sharpe_ratio, 0) / results.length;
  const avgDrawdown = results.reduce((s, r) => s + r.max_drawdown_pct, 0) / results.length;
  const avgComposite = results.reduce((s, r) => s + r.composite_score, 0) / results.length;

  // Find most recent run
  const latest = results.reduce((a, b) => a.created_at > b.created_at ? a : b);

  return {
    score: avgComposite,
    strategies_tested: results.length,
    total_bt_trades: totalBtTrades,
    avg_win_rate: avgWinRate,
    avg_sharpe: avgSharpe,
    avg_drawdown_pct: avgDrawdown,
    data_source: latest.data_source,
    last_run: latest.created_at,
  };
}

// ---------------------------------------------------------------------------
// Gate computation (paper trading metrics — unchanged logic)
// ---------------------------------------------------------------------------

function computeGate(
  gate: GateConfig,
  allTrades: TradeRow[],
  allBacktests: BacktestRow[],
): GateResult {
  const strategySet = new Set(gate.strategies);
  const trades = allTrades.filter((t) => strategySet.has(t.strategy));

  const emptyMetrics = {
    total_trades: 0, wins: 0, losses: 0, breakeven: 0,
    win_rate: 0, total_pnl_cents: 0, avg_pnl_cents: 0,
    best_trade_cents: 0, worst_trade_cents: 0,
    best_trade_ticker: '', worst_trade_ticker: '',
    max_drawdown_pct: 0, profitable_days: 0, total_days: 0,
    current_streak: 0, longest_win_streak: 0, longest_loss_streak: 0,
    daily_pnl: [] as DailyPnl[], strategies_active: 0,
    strategies_total: gate.strategies.length,
    regime_breakdown: [],
  };

  if (trades.length === 0) {
    const btConf = computeBacktestConfidence(gate, allBacktests);
    const paperReadiness = 0;
    const btScore = btConf ? btConf.score / 100 : 0;
    const blended = paperReadiness * PAPER_WEIGHT + btScore * BACKTEST_WEIGHT;

    return {
      label: gate.label,
      platform: gate.platform,
      thresholds: gate.thresholds,
      metrics: emptyMetrics,
      gate_checks: buildGateChecks(gate, 0, 0, 0, 0, 0),
      paper_readiness: 0,
      backtest_confidence: btConf,
      blended_readiness: blended,
    };
  }

  const wins = trades.filter((t) => t.pnl_cents > 0);
  const losses = trades.filter((t) => t.pnl_cents < 0);
  const breakeven = trades.filter((t) => t.pnl_cents === 0);
  const totalPnl = trades.reduce((s, t) => s + t.pnl_cents, 0);
  const winRate = wins.length / trades.length;
  const avgPnl = totalPnl / trades.length;

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
  let currentStreak = 0;
  const lastTrades = [...trades].reverse();
  if (lastTrades.length > 0) {
    const lastSign = lastTrades[0].pnl_cents > 0 ? 1 : -1;
    for (const t of lastTrades) {
      const sign = t.pnl_cents > 0 ? 1 : t.pnl_cents < 0 ? -1 : 0;
      if (sign === lastSign) currentStreak++;
      else break;
    }
    if (lastSign < 0) currentStreak = -currentStreak;
  }

  const activeStrategies = new Set(trades.map((t) => t.strategy));
  const checks = buildGateChecks(gate, trades.length, winRate, ddPct, profitableDays, avgPnl);

  // Paper readiness = ratio of passed gate checks
  const paperReadiness = checks.filter((c) => c.passed).length / checks.length;

  // Backtest confidence
  const btConf = computeBacktestConfidence(gate, allBacktests);
  const btScore = btConf ? btConf.score / 100 : 0;

  // Blended readiness
  const blended = btConf
    ? paperReadiness * PAPER_WEIGHT + btScore * BACKTEST_WEIGHT
    : paperReadiness; // No backtest data = paper only

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
      regime_breakdown: [],
    },
    gate_checks: checks,
    paper_readiness: paperReadiness,
    backtest_confidence: btConf,
    blended_readiness: blended,
  };
}

// ---------------------------------------------------------------------------
// API handler
// ---------------------------------------------------------------------------

export async function GET() {
  try {
    const [kalshiTrades, stockTrades, allBacktests] = await Promise.all([
      fetchClosedTrades(),
      fetchStockTrades(),
      fetchBacktestResults(),
    ]);

    // Route trades to the correct gates:
    // - KALSHI gate uses Kalshi trades (deepstack_trades)
    // - STOCKS/FUTURES/OPTIONS gates use stock trades (deepstack_stock_trades)
    const IBKR_GATES = new Set(['STOCKS', 'FUTURES', 'OPTIONS']);
    const gates = GATES.map((gate) => {
      const trades = IBKR_GATES.has(gate.label) ? stockTrades : kalshiTrades;
      return computeGate(gate, trades, allBacktests);
    });

    return NextResponse.json(
      {
        gates,
        weights: { backtest: BACKTEST_WEIGHT, paper: PAPER_WEIGHT },
      },
      { headers: { 'Cache-Control': 'private, max-age=15' } },
    );
  } catch (error) {
    console.error('Graduation API error:', error);
    return NextResponse.json({ gates: [], weights: { backtest: BACKTEST_WEIGHT, paper: PAPER_WEIGHT } }, { status: 500 });
  }
}

// ---------------------------------------------------------------------------
// Gate check builder
// ---------------------------------------------------------------------------

function buildGateChecks(
  gate: GateConfig,
  trades: number,
  winRate: number,
  drawdownPct: number,
  profitableDays: number,
  avgPnl: number,
) {
  const checks: GateCheck[] = [
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
