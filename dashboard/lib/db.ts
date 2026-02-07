import Database from 'better-sqlite3';
import path from 'path';
import { Trade, DailySummary } from './types';

// Database path - configurable via environment variable
// Falls back to parent directory relative to cwd
const DB_PATH = process.env.KALSHI_JOURNAL_DB
  ? path.resolve(process.env.KALSHI_JOURNAL_DB)
  : path.resolve(process.cwd(), '..', 'trade_journal.db');

// Get database instance
function getDb() {
  return new Database(DB_PATH, { readonly: true, fileMustExist: true });
}

// Get recent trades
export function getRecentTrades(limit: number = 20): Trade[] {
  const db = getDb();
  try {
    const stmt = db.prepare(`
      SELECT * FROM trades
      ORDER BY created_at DESC
      LIMIT ?
    `);
    return stmt.all(limit) as Trade[];
  } finally {
    db.close();
  }
}

// Get trades for today
export function getTodayTrades(): Trade[] {
  const db = getDb();
  try {
    const today = new Date().toISOString().split('T')[0];
    const stmt = db.prepare(`
      SELECT * FROM trades
      WHERE session_date = ?
      ORDER BY created_at DESC
    `);
    return stmt.all(today) as Trade[];
  } finally {
    db.close();
  }
}

// Get active positions (status = 'open')
export function getActivePositions(): Trade[] {
  const db = getDb();
  try {
    const stmt = db.prepare(`
      SELECT * FROM trades
      WHERE status = 'open'
      ORDER BY created_at DESC
    `);
    return stmt.all() as Trade[];
  } finally {
    db.close();
  }
}

// Get daily summary
export function getDailySummary(date?: string): DailySummary | null {
  const db = getDb();
  try {
    const targetDate = date || new Date().toISOString().split('T')[0];
    const stmt = db.prepare(`
      SELECT * FROM daily_summary
      WHERE date = ?
    `);
    return stmt.get(targetDate) as DailySummary | null;
  } finally {
    db.close();
  }
}

// Get recent daily summaries
export function getRecentSummaries(limit: number = 7): DailySummary[] {
  const db = getDb();
  try {
    const stmt = db.prepare(`
      SELECT * FROM daily_summary
      ORDER BY date DESC
      LIMIT ?
    `);
    return stmt.all(limit) as DailySummary[];
  } finally {
    db.close();
  }
}

// Get stats by strategy
export function getStrategyStats(strategy: string): {
  total_trades: number;
  winning_trades: number;
  total_pnl_cents: number;
} {
  const db = getDb();
  try {
    const stmt = db.prepare(`
      SELECT
        COUNT(*) as total_trades,
        SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as winning_trades,
        COALESCE(SUM(pnl_cents), 0) as total_pnl_cents
      FROM trades
      WHERE strategy = ? AND status = 'closed'
    `);
    const result = stmt.get(strategy) as {
      total_trades: number;
      winning_trades: number;
      total_pnl_cents: number;
    };
    return result;
  } finally {
    db.close();
  }
}

// Get total stats
export function getTotalStats(): {
  total_trades: number;
  winning_trades: number;
  total_pnl_cents: number;
  active_positions: number;
} {
  const db = getDb();
  try {
    const stmt = db.prepare(`
      SELECT
        COUNT(*) as total_trades,
        SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as winning_trades,
        COALESCE(SUM(pnl_cents), 0) as total_pnl_cents,
        SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as active_positions
      FROM trades
      WHERE status IN ('closed', 'open')
    `);
    const result = stmt.get() as {
      total_trades: number;
      winning_trades: number;
      total_pnl_cents: number;
      active_positions: number;
    };
    return result;
  } finally {
    db.close();
  }
}
