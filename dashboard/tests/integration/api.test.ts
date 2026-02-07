import { describe, it, expect } from 'vitest';

const BASE_URL = 'http://localhost:3000';

/**
 * API Integration Tests
 *
 * These tests verify API endpoints work correctly against the running server.
 * Prerequisites: The dev server must be running (npm run dev)
 *
 * Note: These tests interact with the actual database configured in .env.local.
 * For isolated testing, run against a test server with DATABASE_URL pointing to kalshi_trading_test.
 */
describe('API Integration Tests', () => {
  describe('GET /api/trades', () => {
    it('should return trades array', async () => {
      const response = await fetch(`${BASE_URL}/api/trades`);
      const data = await response.json();

      expect(response.ok).toBe(true);
      expect(data.trades).toBeDefined();
      expect(Array.isArray(data.trades)).toBe(true);
    });

    it('should return trades with required fields', async () => {
      const response = await fetch(`${BASE_URL}/api/trades`);
      const data = await response.json();

      if (data.trades.length > 0) {
        const trade = data.trades[0];
        expect(trade).toHaveProperty('id');
        expect(trade).toHaveProperty('market_ticker');
        expect(trade).toHaveProperty('side');
        expect(trade).toHaveProperty('status');
      }
    });
  });

  describe('POST /api/trades', () => {
    it('should create a new trade', async () => {
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

      const response = await fetch(`${BASE_URL}/api/trades`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newTrade),
      });

      expect(response.status).toBe(201);

      const data = await response.json();
      expect(data.trade).toBeDefined();
      expect(data.trade.market_ticker).toBe(newTrade.market_ticker);
      expect(data.trade.id).toBeDefined();
    });
  });

  describe('PATCH /api/trades', () => {
    it('should return 400 without trade ID', async () => {
      const response = await fetch(`${BASE_URL}/api/trades`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'closed' }),
      });

      expect(response.status).toBe(400);
    });
  });

  describe('GET /api/status', () => {
    it('should return dashboard state', async () => {
      const response = await fetch(`${BASE_URL}/api/status`);
      const data = await response.json();

      expect(response.ok).toBe(true);
      expect(data.timestamp).toBeDefined();
      expect(data.account).toBeDefined();
      expect(data.risk).toBeDefined();
      expect(data.strategies).toBeDefined();
    });

    it('should include strategy array', async () => {
      const response = await fetch(`${BASE_URL}/api/status`);
      const data = await response.json();

      expect(Array.isArray(data.strategies)).toBe(true);
    });
  });

  describe('GET /api/opportunities', () => {
    it('should return opportunities array', async () => {
      const response = await fetch(`${BASE_URL}/api/opportunities`);
      const data = await response.json();

      expect(response.ok).toBe(true);
      expect(data.opportunities).toBeDefined();
      expect(Array.isArray(data.opportunities)).toBe(true);
    });

    it('should support status filter', async () => {
      const response = await fetch(`${BASE_URL}/api/opportunities?status=active`);
      const data = await response.json();

      expect(response.ok).toBe(true);
      data.opportunities.forEach((opp: { status: string }) => {
        expect(opp.status).toBe('active');
      });
    });
  });

  describe('POST /api/opportunities', () => {
    it('should create a new opportunity', async () => {
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

      const response = await fetch(`${BASE_URL}/api/opportunities`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newOpp),
      });

      expect(response.status).toBe(201);

      const data = await response.json();
      expect(data.opportunity.market_ticker).toBe(newOpp.market_ticker);
      expect(data.opportunity.status).toBe('active');
    });
  });

  describe('GET /api/feed', () => {
    it('should return log entries array', async () => {
      const response = await fetch(`${BASE_URL}/api/feed`);
      const data = await response.json();

      expect(response.ok).toBe(true);
      expect(data.logs).toBeDefined();
      expect(Array.isArray(data.logs)).toBe(true);
    });
  });

  describe('POST /api/feed', () => {
    it('should create a new log entry', async () => {
      const newLog = {
        level: 'INFO',
        strategy: 'test_strategy',
        message: `API test log entry ${Date.now()}`,
      };

      const response = await fetch(`${BASE_URL}/api/feed`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newLog),
      });

      expect(response.status).toBe(201);

      const data = await response.json();
      expect(data.success).toBe(true);
    });
  });
});
