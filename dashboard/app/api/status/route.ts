import { NextResponse } from 'next/server';
import { getLatestDashboardState, getTotalStats, getAllStrategyStats, getStrategies, saveDashboardState } from '@/lib/db-postgres';
import { DashboardState } from '@/lib/types';
import { DashboardStateSchema } from '@/lib/validation';

// Default state when no data exists
const DEFAULT_STATE: DashboardState = {
  timestamp: new Date().toISOString(),
  account: {
    balance_cents: 10000, // $100 starting balance
    daily_pnl_cents: 0,
    daily_pnl_percentage: 0,
    total_positions: 0,
    available_balance_cents: 10000,
  },
  risk: {
    daily_loss_limit_cents: 10000,
    daily_loss_used_cents: 0,
    max_position_size_cents: 5000,
    kelly_fraction: 0.5,
    positions_at_risk: 0,
    risk_percentage: 0,
  },
  strategies: [
    { name: 'mean_reversion', enabled: true, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'combinatorial_arbitrage', enabled: true, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'cross_platform_arbitrage', enabled: true, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
  ],
};

export async function GET() {
  try {
    // Try to get latest state from PostgreSQL
    let state = await getLatestDashboardState();

    if (!state) {
      // No state in DB, use default and try to enrich with stats
      state = { ...DEFAULT_STATE };
    }

    // Enrich with real-time stats from trades table
    // Uses aggregated query to avoid N+1 problem
    try {
      const [totalStats, strategies, allStrategyStats] = await Promise.all([
        getTotalStats(),
        getStrategies(),
        getAllStrategyStats(),
      ]);

      state.account.total_positions = totalStats.active_positions ?? 0;

      // Merge strategy stats in memory (no additional queries)
      if (strategies.length > 0) {
        state.strategies = strategies.map((strategy) => {
          const stats = allStrategyStats[strategy.name];
          return {
            ...strategy,
            active_positions: stats?.total_trades ?? strategy.active_positions,
          };
        });
      }
    } catch (statsError) {
      console.error('Error enriching with stats:', statsError);
    }

    return NextResponse.json(state);
  } catch (error) {
    console.error('Error reading dashboard state:', error);
    return NextResponse.json(DEFAULT_STATE);
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();

    // Validate input
    const result = DashboardStateSchema.safeParse(body);
    if (!result.success) {
      return NextResponse.json(
        { error: `Validation failed: ${result.error.message}` },
        { status: 400 }
      );
    }

    await saveDashboardState(result.data as DashboardState);
    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error saving dashboard state:', error);
    return NextResponse.json({ error: 'Failed to save state' }, { status: 500 });
  }
}
