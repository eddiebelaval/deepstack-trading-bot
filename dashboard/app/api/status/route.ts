import { NextResponse } from 'next/server';
import { getLatestDashboardState, getStrategies, getPositions, saveDashboardState } from '@/lib/db-postgres';
import { DashboardState } from '@/lib/types';
import { DashboardStateSchema } from '@/lib/validation';

// Default state when no data exists
const DEFAULT_STATE: DashboardState = {
  timestamp: new Date().toISOString(),
  account: {
    balance_cents: 0,
    daily_pnl_cents: 0,
    daily_pnl_percentage: 0,
    total_positions: 0,
    available_balance_cents: 0,
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
    // Original strategies
    { name: 'mean_reversion', enabled: true, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'momentum', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'combinatorial_arbitrage', enabled: true, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'cross_platform_arbitrage', enabled: true, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    // Prediction market strategies (disabled by default)
    { name: 'high_probability_bonds', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'calibration_edge', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'weather_aggregation', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'news_sentiment_fade', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'correlated_event_arbitrage', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'domain_specialization', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    // New strategies (Feb 2026)
    { name: 'crypto_intraday', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'bear_macro', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
    { name: 'market_making', enabled: false, active_positions: 0, opportunities_found: 0, last_scan: null, status: 'inactive' },
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

    // Enrich with live data from Supabase
    try {
      const [strategies, positions] = await Promise.all([
        getStrategies(),
        getPositions(),
      ]);

      // Use actual exchange positions (not stale trades table)
      state.account.total_positions = positions.length;

      // Use strategy_status rows if available, otherwise fall back to defaults
      state.strategies = strategies.length > 0 ? strategies : DEFAULT_STATE.strategies;
    } catch (statsError) {
      console.error('Error enriching with stats:', statsError);
    }

    return NextResponse.json(state);
  } catch (error) {
    console.error('Error reading dashboard state:', error);
    return NextResponse.json(
      { error: 'Database unavailable', fallback: DEFAULT_STATE },
      { status: 503 }
    );
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
