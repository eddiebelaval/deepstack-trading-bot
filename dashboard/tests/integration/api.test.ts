import { describe, it, expect, beforeAll, beforeEach, afterAll } from 'vitest';
import { Pool } from 'pg';
import { clearTestData } from '../fixtures/seed';

import * as tradesRoute from '../../app/api/trades/route';
import * as statusRoute from '../../app/api/status/route';
import * as opportunitiesRoute from '../../app/api/opportunities/route';
import * as feedRoute from '../../app/api/feed/route';

// These tests run the Next route handlers directly (no external server needed).
// They still hit the real test database.

const pool = new Pool({
  host: 'localhost',
  port: 5432,
  database: 'kalshi_trading_test',
});

describe('API Route Handler Integration', () => {
  beforeAll(async () => {
    await clearTestData(pool);
  });

  beforeEach(async () => {
    await clearTestData(pool);
  });

  afterAll(async () => {
    await pool.end();
  });

  describe('Trades', () => {
    it('GET /api/trades returns trades array', async () => {
      const res = await tradesRoute.GET(new Request('http://localhost/api/trades'));
      const data = await res.json();

      expect(res.ok).toBe(true);
      expect(Array.isArray(data.trades)).toBe(true);
    });

    it('POST /api/trades creates a trade', async () => {
      const newTrade = {
        market_ticker: `TEST-${Date.now()}`,
        side: 'YES',
        action: 'BUY',
        contracts: 1,
        entry_price_cents: 50,
        status: 'open',
        strategy: 'test_strategy',
        reasoning: 'API test trade',
      };

      const res = await tradesRoute.POST(
        new Request('http://localhost/api/trades', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newTrade),
        })
      );

      expect(res.status).toBe(201);
      const data = await res.json();
      expect(data.trade).toBeDefined();
      expect(data.trade.market_ticker).toBe(newTrade.market_ticker);
      expect(data.trade.id).toBeDefined();
    });

    it('PATCH /api/trades returns 400 without trade id', async () => {
      const res = await tradesRoute.PATCH(
        new Request('http://localhost/api/trades', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'closed' }),
        })
      );
      expect(res.status).toBe(400);
    });
  });

  describe('Status', () => {
    it('GET /api/status returns dashboard state shape', async () => {
      const res = await statusRoute.GET();
      const data = await res.json();

      expect(res.ok).toBe(true);
      expect(data.timestamp).toBeDefined();
      expect(data.account).toBeDefined();
      expect(data.risk).toBeDefined();
      expect(Array.isArray(data.strategies)).toBe(true);
    });
  });

  describe('Opportunities', () => {
    it('GET /api/opportunities returns opportunities array', async () => {
      const res = await opportunitiesRoute.GET(
        new Request('http://localhost/api/opportunities')
      );
      const data = await res.json();

      expect(res.ok).toBe(true);
      expect(Array.isArray(data.opportunities)).toBe(true);
    });

    it('POST /api/opportunities creates an opportunity', async () => {
      const newOpp = {
        market_ticker: `OPP-TEST-${Date.now()}`,
        strategy: 'momentum',
        side: 'YES',
        current_price_cents: 35,
        target_price_cents: 50,
        expected_profit_pct: 42.8,
        confidence: 0.75,
        reasoning: 'API test opportunity',
      };

      const res = await opportunitiesRoute.POST(
        new Request('http://localhost/api/opportunities', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newOpp),
        })
      );

      expect(res.status).toBe(201);
      const data = await res.json();
      expect(data.opportunity.market_ticker).toBe(newOpp.market_ticker);
      expect(data.opportunity.status).toBe('active');
    });
  });

  describe('Feed', () => {
    it('GET /api/feed returns logs array', async () => {
      const res = await feedRoute.GET();
      const data = await res.json();

      expect(res.ok).toBe(true);
      expect(Array.isArray(data.logs)).toBe(true);
    });

    it('POST /api/feed creates a log entry', async () => {
      const newLog = {
        level: 'INFO',
        strategy: 'test_strategy',
        message: `API test log entry ${Date.now()}`,
      };

      const res = await feedRoute.POST(
        new Request('http://localhost/api/feed', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newLog),
        })
      );

      expect(res.status).toBe(201);
      const data = await res.json();
      expect(data.success).toBe(true);
    });
  });
});

