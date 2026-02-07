import { Pool } from 'pg';
import fs from 'fs';
import path from 'path';
import dotenv from 'dotenv';
import { getPoolConfig } from '../lib/postgres';

dotenv.config({ path: path.join(__dirname, '..', '.env.local') });

async function runMigrations(): Promise<void> {
  const pool = new Pool(getPoolConfig());

  const client = await pool.connect();

  try {
    console.log('Running migrations...\n');

    // Create migrations tracking table
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        id SERIAL PRIMARY KEY,
        filename VARCHAR(255) UNIQUE NOT NULL,
        executed_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);

    // Get list of migration files
    const migrationsDir = path.join(__dirname, '..', 'lib', 'migrations');
    const files = fs.readdirSync(migrationsDir)
      .filter(f => f.endsWith('.sql'))
      .sort();

    // Get already executed migrations
    const executed = await client.query(
      'SELECT filename FROM schema_migrations'
    );
    const executedSet = new Set(executed.rows.map(r => r.filename));

    // Run pending migrations
    for (const file of files) {
      if (executedSet.has(file)) {
        console.log(`[SKIP] ${file} (already executed)`);
        continue;
      }

      console.log(`[RUN]  ${file}`);
      const sql = fs.readFileSync(path.join(migrationsDir, file), 'utf-8');

      await client.query('BEGIN');
      try {
        await client.query(sql);
        await client.query(
          'INSERT INTO schema_migrations (filename) VALUES ($1)',
          [file]
        );
        await client.query('COMMIT');
        console.log(`[OK]   ${file}`);
      } catch (error) {
        await client.query('ROLLBACK');
        console.error(`[FAIL] ${file}:`, error);
        throw error;
      }
    }

    console.log('\nMigrations complete!');
  } finally {
    client.release();
    await pool.end();
  }
}

// Run if called directly
runMigrations().catch(err => {
  console.error('Migration failed:', err);
  process.exit(1);
});
