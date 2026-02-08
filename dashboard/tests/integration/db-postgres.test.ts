import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest';
import { Pool } from 'pg';
import { seedTestData, clearTestData } from '../fixtures/seed';

// Test database pool - explicitly use test database
const pool = new Pool({
  host: 'localhost',
  port: 5432,
  database: 'kalshi_trading_test',
});

describe('Database Integration Tests', () => {
  beforeAll(async () => {
    // Ensure clean state at start
    await clearTestData(pool);
  });

  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    await clearTestData(pool);
  });

  describe('Trades', () => {
    it('should create and retrieve trades', async () => {
      const { trades } = await seedTestData(pool);

      const result = await pool.query('SELECT * FROM deepstack_trades ORDER BY id');
      expect(result.rows).toHaveLength(5);
      expect(result.rows[0].market_ticker).toBe('INXD-27JAN27-5400');
    });

    it('should filter trades by status', async () => {
      await seedTestData(pool);

      const openTrades = await pool.query(
        "SELECT * FROM deepstack_trades WHERE status = 'open'"
      );
      expect(openTrades.rows).toHaveLength(1);

      const closedTrades = await pool.query(
        "SELECT * FROM deepstack_trades WHERE status = 'closed'"
      );
      expect(closedTrades.rows).toHaveLength(4);
    });

    it('should calculate strategy stats correctly', async () => {
      await seedTestData(pool);

      const result = await pool.query(`
        SELECT
          COUNT(*)::int as total_trades,
          COALESCE(SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END), 0)::int as winning_trades,
          COALESCE(SUM(pnl_cents), 0)::int as total_pnl_cents
        FROM deepstack_trades
        WHERE strategy = 'momentum' AND status = 'closed'
      `);

      expect(result.rows[0].total_trades).toBe(2);
      expect(result.rows[0].winning_trades).toBe(1);
      expect(result.rows[0].total_pnl_cents).toBe(50); // 250 - 200
    });

    it('should update trade status and P&L', async () => {
      const { trades } = await seedTestData(pool);
      const openTrade = trades.find(t => t.status === 'open');

      await pool.query(
        `UPDATE deepstack_trades SET status = 'closed', pnl_cents = 300, exit_price_cents = 52
         WHERE id = $1`,
        [openTrade?.id]
      );

      const result = await pool.query('SELECT * FROM deepstack_trades WHERE id = $1', [openTrade?.id]);
      expect(result.rows[0].status).toBe('closed');
      expect(result.rows[0].pnl_cents).toBe(300);
      expect(result.rows[0].exit_price_cents).toBe(52);
    });
  });

  describe('Opportunities', () => {
    it('should create and retrieve opportunities', async () => {
      const { opportunities } = await seedTestData(pool);

      expect(opportunities).toHaveLength(4);
      expect(opportunities[0].status).toBe('active');
    });

    it('should filter opportunities by status', async () => {
      await seedTestData(pool);

      const active = await pool.query(
        "SELECT * FROM deepstack_opportunities WHERE status = 'active'"
      );
      expect(active.rows).toHaveLength(2);

      const taken = await pool.query(
        "SELECT * FROM deepstack_opportunities WHERE status = 'taken'"
      );
      expect(taken.rows).toHaveLength(1);
    });

    it('should update opportunity status to taken with trade reference', async () => {
      const { opportunities, trades } = await seedTestData(pool);
      const activeOpp = opportunities.find(o => o.status === 'active');

      await pool.query(
        `UPDATE deepstack_opportunities
         SET status = 'taken', taken_at = NOW(), trade_id = $1
         WHERE id = $2`,
        [trades[0].id, activeOpp?.id]
      );

      const result = await pool.query('SELECT * FROM deepstack_opportunities WHERE id = $1', [activeOpp?.id]);
      expect(result.rows[0].status).toBe('taken');
      expect(result.rows[0].trade_id).toBe(trades[0].id);
      expect(result.rows[0].taken_at).not.toBeNull();
    });
  });

  describe('Log Entries', () => {
    it('should store and retrieve log entries', async () => {
      await seedTestData(pool);

      const result = await pool.query(
        'SELECT * FROM deepstack_log_entries ORDER BY timestamp DESC LIMIT 10'
      );
      expect(result.rows).toHaveLength(5);
    });

    it('should filter logs by level', async () => {
      await seedTestData(pool);

      const errors = await pool.query(
        "SELECT * FROM deepstack_log_entries WHERE level = 'ERROR'"
      );
      expect(errors.rows).toHaveLength(1);
      expect(errors.rows[0].message).toContain('rate limit');
    });

    it('should filter logs by strategy', async () => {
      await seedTestData(pool);

      const momentumLogs = await pool.query(
        "SELECT * FROM deepstack_log_entries WHERE strategy = 'momentum'"
      );
      expect(momentumLogs.rows).toHaveLength(3);
    });
  });

  describe('Dashboard State', () => {
    it('should save and retrieve dashboard state', async () => {
      await pool.query(`
        INSERT INTO deepstack_dashboard_state (
          balance_cents, daily_pnl_cents, daily_pnl_percentage,
          total_positions, available_balance_cents,
          daily_loss_limit_cents, daily_loss_used_cents,
          max_position_size_cents, kelly_fraction,
          positions_at_risk, risk_percentage
        ) VALUES (10000, 500, 5.0, 2, 8000, 10000, 500, 5000, 0.5, 1, 10.0)
      `);

      const result = await pool.query(
        'SELECT * FROM deepstack_dashboard_state ORDER BY timestamp DESC LIMIT 1'
      );

      expect(result.rows[0].balance_cents).toBe(10000);
      expect(result.rows[0].daily_pnl_cents).toBe(500);
      expect(result.rows[0].total_positions).toBe(2);
    });
  });

  describe('Strategy Status', () => {
    it('should have default strategies from migration', async () => {
      const result = await pool.query('SELECT * FROM deepstack_strategy_status ORDER BY name');

      expect(result.rows.length).toBeGreaterThanOrEqual(4);
      expect(result.rows.map(r => r.name)).toContain('momentum');
      expect(result.rows.map(r => r.name)).toContain('mean_reversion');
    });

    it('should update strategy status', async () => {
      await pool.query(`
        UPDATE deepstack_strategy_status
        SET status = 'active', opportunities_found = 5, last_scan = NOW()
        WHERE name = 'momentum'
      `);

      const result = await pool.query(
        "SELECT * FROM deepstack_strategy_status WHERE name = 'momentum'"
      );

      expect(result.rows[0].status).toBe('active');
      expect(result.rows[0].opportunities_found).toBe(5);
      expect(result.rows[0].last_scan).not.toBeNull();
    });
  });

  describe('Data Integrity', () => {
    it('should enforce foreign key on opportunity.trade_id', async () => {
      await seedTestData(pool);

      // This should fail - invalid trade_id
      await expect(
        pool.query(`
          INSERT INTO deepstack_opportunities (market_ticker, strategy, side, current_price_cents, target_price_cents, trade_id)
          VALUES ('TEST', 'test', 'YES', 50, 60, 99999)
        `)
      ).rejects.toThrow();
    });

    it('should enforce check constraints on side values', async () => {
      await expect(
        pool.query(`
          INSERT INTO deepstack_trades (market_ticker, side, action, contracts, entry_price_cents, strategy)
          VALUES ('TEST', 'INVALID', 'BUY', 1, 50, 'test')
        `)
      ).rejects.toThrow();
    });

    it('should auto-update updated_at on trades', async () => {
      const { trades } = await seedTestData(pool);
      const trade = trades[0];

      // Wait a moment then update
      await new Promise(resolve => setTimeout(resolve, 100));

      await pool.query(
        'UPDATE deepstack_trades SET pnl_cents = 999 WHERE id = $1',
        [trade.id]
      );

      const result = await pool.query('SELECT created_at, updated_at FROM deepstack_trades WHERE id = $1', [trade.id]);
      expect(new Date(result.rows[0].updated_at).getTime())
        .toBeGreaterThan(new Date(result.rows[0].created_at).getTime());
    });
  });
});
