import { Pool } from 'pg';

export interface TestData {
  trades: Array<{
    id: number;
    market_ticker: string;
    side: string;
    action: string;
    contracts: number;
    entry_price_cents: number;
    pnl_cents: number | null;
    status: string;
    strategy: string;
  }>;
  opportunities: Array<{
    id: number;
    market_ticker: string;
    strategy: string;
    side: string;
    current_price_cents: number;
    target_price_cents: number;
    status: string;
  }>;
}

export async function seedTestData(pool: Pool): Promise<TestData> {
  // Insert test trades
  const tradesResult = await pool.query(`
    INSERT INTO trades (market_ticker, side, action, contracts, entry_price_cents, pnl_cents, status, strategy, session_date)
    VALUES
      ('INXD-27JAN27-5400', 'YES', 'BUY', 5, 45, 250, 'closed', 'momentum', CURRENT_DATE),
      ('INXD-27JAN27-5375', 'NO', 'BUY', 3, 55, -150, 'closed', 'mean_reversion', CURRENT_DATE),
      ('INXD-27JAN27-5425', 'YES', 'BUY', 4, 38, NULL, 'open', 'momentum', CURRENT_DATE),
      ('INXD-27JAN27-5350', 'YES', 'BUY', 2, 62, 180, 'closed', 'combinatorial_arbitrage', CURRENT_DATE),
      ('INXD-27JAN27-5450', 'NO', 'BUY', 6, 48, -200, 'closed', 'momentum', CURRENT_DATE)
    RETURNING id, market_ticker, side, action, contracts, entry_price_cents, pnl_cents, status, strategy
  `);

  // Insert test opportunities
  const opportunitiesResult = await pool.query(`
    INSERT INTO opportunities (market_ticker, strategy, side, current_price_cents, target_price_cents, expected_profit_pct, confidence, status, reasoning)
    VALUES
      ('INXD-27JAN27-5400', 'momentum', 'YES', 42, 55, 31.0, 0.78, 'active', 'RSI oversold at 28'),
      ('INXD-27JAN27-5375', 'mean_reversion', 'NO', 67, 50, 34.0, 0.82, 'active', 'Overbought condition'),
      ('INXD-27JAN27-5425', 'cross_platform_arbitrage', 'YES', 38, 45, 18.4, 0.91, 'taken', 'Polymarket spread detected'),
      ('INXD-27JAN27-5350', 'momentum', 'YES', 23, 35, 52.2, 0.65, 'expired', 'Low liquidity')
    RETURNING id, market_ticker, strategy, side, current_price_cents, target_price_cents, status
  `);

  // Insert log entries
  await pool.query(`
    INSERT INTO log_entries (level, strategy, message)
    VALUES
      ('INFO', 'momentum', 'Strategy initialized'),
      ('INFO', 'momentum', 'Scanning for opportunities'),
      ('WARNING', 'mean_reversion', 'High volatility detected'),
      ('INFO', 'momentum', 'Opportunity found: INXD-27JAN27-5400'),
      ('ERROR', 'cross_platform_arbitrage', 'API rate limit reached')
  `);

  return {
    trades: tradesResult.rows,
    opportunities: opportunitiesResult.rows,
  };
}

export async function clearTestData(pool: Pool): Promise<void> {
  await pool.query(`
    TRUNCATE trades, opportunities, log_entries, dashboard_state,
    market_snapshots, performance_metrics RESTART IDENTITY CASCADE
  `);
}
