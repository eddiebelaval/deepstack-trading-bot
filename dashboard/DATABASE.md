# PostgreSQL Database Setup

## Quick Start

### 1. Install PostgreSQL (if not installed)

**macOS (Homebrew):**
```bash
brew install postgresql@16
brew services start postgresql@16
```

**Or use Postgres.app:** https://postgresapp.com/

### 2. Create the database

```bash
createdb kalshi_trading
```

### 3. Configure environment

```bash
cp .env.example .env.local
# Edit .env.local with your PostgreSQL credentials
```

### 4. Run migrations

```bash
npm run db:migrate
```

## Database Commands

| Command | Description |
|---------|-------------|
| `npm run db:migrate` | Run pending migrations |
| `npm run db:setup` | Create database + run migrations |
| `npm run db:reset` | Drop and recreate database (DATA LOSS!) |

## Schema Overview

| Table | Purpose |
|-------|---------|
| `trades` | All trading activity |
| `daily_summary` | Daily P&L aggregations |
| `opportunities` | Detected trading opportunities |
| `dashboard_state` | Snapshot of account/risk metrics |
| `strategy_status` | Strategy configuration and status |
| `log_entries` | Persistent log feed |
| `market_snapshots` | Historical market data |
| `performance_metrics` | Aggregated performance stats |

## Using Supabase (Alternative)

If you prefer cloud PostgreSQL:

1. Create a project at https://supabase.com
2. Get your connection string from Settings > Database
3. Update `.env.local`:
   ```
   DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres
   ```
4. Run migrations: `npm run db:migrate`

## Troubleshooting

**"Connection refused"**
- Ensure PostgreSQL is running: `brew services list` or `pg_isready`
- Check your `PGHOST` and `PGPORT` settings

**"Database does not exist"**
- Run `createdb kalshi_trading` or `npm run db:setup`

**"Permission denied"**
- Check your `PGUSER` has permissions to the database
- Default macOS user usually has superuser access

## Migration Files

Migrations are in `lib/migrations/` and tracked in the `schema_migrations` table.
Each migration runs once and is recorded to prevent re-execution.
