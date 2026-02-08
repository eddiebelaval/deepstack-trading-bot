// Postgres client for dashboard server routes.
//
// This replaces the previous Supabase PostgREST + service-role approach.
// Use a least-privilege DB user via DATABASE_URL_DASHBOARD.
//
// Notes:
// - This module is server-only. Do not import from client components.
// - We intentionally avoid printing connection details in errors.

import { Pool } from 'pg';

let _pool: Pool | null = null;

function getDatabaseUrl(): string {
  const explicit =
    process.env.DATABASE_URL_DASHBOARD || process.env.DATABASE_URL || '';
  if (explicit) return explicit;

  // Fallback to PG* env vars (useful for local scripts like migrations).
  const db = process.env.PGDATABASE || '';
  if (!db) return '';
  const host = process.env.PGHOST || 'localhost';
  const port = process.env.PGPORT || '5432';
  const user = process.env.PGUSER || '';
  const pass = process.env.PGPASSWORD || '';

  const auth =
    user && pass
      ? `${encodeURIComponent(user)}:${encodeURIComponent(pass)}@`
      : user
        ? `${encodeURIComponent(user)}@`
        : '';

  return `postgresql://${auth}${host}:${port}/${db}`;
}

// For scripts (migrations) that want to construct their own Pool instance.
export function getPoolConfig(): { connectionString: string } {
  const connectionString = getDatabaseUrl();
  if (!connectionString) {
    throw new Error(
      'Database URL is required (set DATABASE_URL_DASHBOARD or DATABASE_URL)'
    );
  }
  return { connectionString };
}

export function getPool(): Pool {
  if (_pool) return _pool;

  _pool = new Pool({
    ...getPoolConfig(),
    statement_timeout: 10_000,
    query_timeout: 10_000,
    connectionTimeoutMillis: 5_000,
    max: 10,
  });

  return _pool;
}

export async function query<T = unknown>(
  text: string,
  params: unknown[] = []
): Promise<{ rows: T[] }> {
  const pool = getPool();
  const res = await pool.query(text, params);
  return { rows: res.rows as T[] };
}

export async function healthCheck(): Promise<boolean> {
  try {
    await query('select 1 as ok');
    return true;
  } catch {
    return false;
  }
}
