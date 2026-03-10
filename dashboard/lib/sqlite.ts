import Database from 'better-sqlite3';
import path from 'path';

const DB_PATH = path.resolve(process.cwd(), '..', 'trade_journal.db');

export function getDb() {
  return new Database(DB_PATH, { readonly: true });
}

/**
 * Execute a callback with a DB connection that is guaranteed to close,
 * even if the callback throws.
 */
export function withDb<T>(fn: (db: InstanceType<typeof Database>) => T): T {
  const db = getDb();
  try {
    return fn(db);
  } finally {
    db.close();
  }
}
