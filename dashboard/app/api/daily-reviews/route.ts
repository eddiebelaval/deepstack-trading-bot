import { NextRequest, NextResponse } from 'next/server';
import { restGet } from '@/lib/postgres';
import type { Trade, CaptainsLogEntry, DailyReview } from '@/lib/types';
import { truncateNote } from '@/lib/format';

export const dynamic = 'force-dynamic';

function computeGrade(
  winRate: number,
  netPnl: number,
  totalTrades: number,
): { grade: DailyReview['grade']; reasons: string[] } {
  const reasons: string[] = [];
  let score = 0;

  // Win rate component (0-40 points)
  if (winRate >= 0.6) {
    score += 40;
    reasons.push('Strong win rate above 60%');
  } else if (winRate >= 0.5) {
    score += 30;
    reasons.push('Positive win rate');
  } else if (winRate >= 0.4) {
    score += 15;
    reasons.push('Win rate below 50% — review entry criteria');
  } else if (totalTrades > 0) {
    reasons.push('Poor win rate — strategies need recalibration');
  }

  // PnL component (0-40 points)
  if (netPnl > 500) {
    score += 40;
    reasons.push(`Strong profit day: +$${(netPnl / 100).toFixed(2)}`);
  } else if (netPnl > 100) {
    score += 30;
    reasons.push('Modest profit');
  } else if (netPnl >= 0) {
    score += 20;
    reasons.push('Breakeven or marginal gain');
  } else if (netPnl > -500) {
    score += 10;
    reasons.push('Small loss — within acceptable range');
  } else {
    reasons.push(`Significant loss: -$${(Math.abs(netPnl) / 100).toFixed(2)}`);
  }

  // Activity component (0-20 points)
  if (totalTrades >= 5) {
    score += 20;
    reasons.push('Good trade volume');
  } else if (totalTrades >= 2) {
    score += 15;
    reasons.push('Moderate activity');
  } else if (totalTrades >= 1) {
    score += 10;
    reasons.push('Low activity day');
  } else {
    reasons.push('No trades executed');
  }

  let grade: DailyReview['grade'];
  if (score >= 85) grade = 'A';
  else if (score >= 70) grade = 'B';
  else if (score >= 50) grade = 'C';
  else if (score >= 30) grade = 'D';
  else grade = 'F';

  return { grade, reasons };
}

function buildReviewForDate(
  date: string,
  trades: Trade[],
  logEntries: CaptainsLogEntry[],
): DailyReview {
  const dayTrades = trades.filter(
    (t) => t.session_date === date || t.created_at.startsWith(date),
  );
  const closedTrades = dayTrades.filter(
    (t) => t.status === 'closed' && t.pnl_cents != null,
  );

  const wins = closedTrades.filter((t) => (t.pnl_cents ?? 0) > 0);
  const losses = closedTrades.filter((t) => (t.pnl_cents ?? 0) < 0);
  const netPnl = closedTrades.reduce((sum, t) => sum + (t.pnl_cents ?? 0), 0);
  const winRate =
    closedTrades.length > 0 ? wins.length / closedTrades.length : 0;

  // Best and worst trades
  let bestTrade: DailyReview['best_trade'] = null;
  let worstTrade: DailyReview['worst_trade'] = null;
  if (closedTrades.length > 0) {
    const sorted = [...closedTrades].sort(
      (a, b) => (b.pnl_cents ?? 0) - (a.pnl_cents ?? 0),
    );
    const best = sorted[0];
    const worst = sorted[sorted.length - 1];
    if ((best.pnl_cents ?? 0) > 0) {
      bestTrade = {
        ticker: best.market_ticker,
        pnl_cents: best.pnl_cents!,
        strategy: best.strategy,
      };
    }
    if ((worst.pnl_cents ?? 0) < 0) {
      worstTrade = {
        ticker: worst.market_ticker,
        pnl_cents: worst.pnl_cents!,
        strategy: worst.strategy,
      };
    }
  }

  // Strategy breakdown
  const stratMap: Record<
    string,
    { trades: number; wins: number; pnl_cents: number }
  > = {};
  for (const t of closedTrades) {
    if (!stratMap[t.strategy])
      stratMap[t.strategy] = { trades: 0, wins: 0, pnl_cents: 0 };
    stratMap[t.strategy].trades++;
    if ((t.pnl_cents ?? 0) > 0) stratMap[t.strategy].wins++;
    stratMap[t.strategy].pnl_cents += t.pnl_cents ?? 0;
  }
  const strategyBreakdown = Object.entries(stratMap)
    .map(([name, s]) => ({ name, ...s }))
    .sort((a, b) => b.pnl_cents - a.pnl_cents);

  // Regime from captain's log
  const dayLogs = logEntries.filter((e) => e.created_at.startsWith(date));
  const regimeLogs = dayLogs.filter((e) => e.regime != null && e.regime !== '');
  const latestRegime =
    regimeLogs.length > 0 ? regimeLogs[regimeLogs.length - 1].regime : null;

  // Highlights: significant bot entries for the day
  const highlights = dayLogs
    .filter(
      (e) =>
        e.role === 'bot' &&
        (e.priority === 'critical' || e.priority === 'significant'),
    )
    .slice(0, 5)
    .map((e) => truncateNote(e.content, 120));

  const { grade, reasons } = computeGrade(winRate, netPnl, closedTrades.length);

  return {
    date,
    total_trades: dayTrades.length,
    winning_trades: wins.length,
    losing_trades: losses.length,
    net_pnl_cents: netPnl,
    win_rate: winRate,
    best_trade: bestTrade,
    worst_trade: worstTrade,
    strategy_breakdown: strategyBreakdown,
    regime: latestRegime,
    regime_changes: regimeLogs.length,
    highlights,
    grade,
    grade_reasons: reasons,
  };
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const days = Math.min(
      parseInt(searchParams.get('days') || '7', 10),
      30,
    );

    // Fetch trades and log entries for the date range
    const trades = await restGet<Trade>(
      'deepstack_trades',
      `order=created_at.desc&limit=1000`,
    );
    const logEntries = await restGet<CaptainsLogEntry>(
      'deepstack_captains_log',
      `order=created_at.desc&limit=500`,
    );

    // Generate date list (last N days)
    const dates: string[] = [];
    for (let i = 0; i < days; i++) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      dates.push(d.toISOString().split('T')[0]);
    }

    // Build reviews for each day that has activity
    const reviews: DailyReview[] = [];
    for (const date of dates) {
      const review = buildReviewForDate(date, trades, logEntries);
      // Only include days with some activity (trades or log entries)
      if (review.total_trades > 0 || review.highlights.length > 0) {
        reviews.push(review);
      }
    }

    return NextResponse.json(
      { reviews },
      { headers: { 'Cache-Control': 'private, max-age=60' } },
    );
  } catch (error) {
    console.error('Error computing daily reviews:', error);
    return NextResponse.json({ reviews: [] }, { status: 500 });
  }
}
