import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

const DB_PATH = path.resolve(process.cwd(), '..', 'trade_journal.db');

export function isDbAvailable(): boolean {
  return fs.existsSync(DB_PATH);
}

export function getDb() {
  return new Database(DB_PATH, { readonly: true });
}

/**
 * Execute a callback with a DB connection that is guaranteed to close,
 * even if the callback throws. Returns null if the DB file doesn't exist
 * (e.g. on Vercel where SQLite is not available).
 */
export function withDb<T>(fn: (db: InstanceType<typeof Database>) => T): T | null {
  if (!isDbAvailable()) return null;
  const db = getDb();
  try {
    return fn(db);
  } finally {
    db.close();
  }
}
