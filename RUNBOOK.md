# DeepStack (Kalshi) Trading Bot Runbook

## Secrets / Local Files
- Do not keep secrets inside the git repo directory.
- Default secret file locations (override with env vars):
  - Bot env: `~/Library/Application Support/deepstack/kalshi-trading.env`
    - Override: `DEEPSTACK_BOT_ENV_PATH`
  - Dashboard env (optional): `~/Library/Application Support/deepstack/kalshi-trading.dashboard.env.local`
    - Override: `DEEPSTACK_DASHBOARD_ENV_PATH`
  - Kalshi private key: `~/Library/Application Support/deepstack/kalshi_private_key.pem`

## Required Environment Variables
### Bot
- `KALSHI_API_KEY_ID`
- `KALSHI_PRIVATE_KEY_PATH` (recommended: the external path above)
- `BOT_COMMAND_HMAC_SECRET` (shared with dashboard for command signing)
- `DATABASE_URL_BOT` (Postgres URL with bot least-privilege permissions)
- Optional (legacy fallback; disabled by default):
  - `DEEPSTACK_ALLOW_POSTGREST=1` to allow Supabase PostgREST polling
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY` (avoid using in production; prefer least-privilege Postgres)

### Dashboard (server-side)
- `BOT_COMMAND_HMAC_SECRET` (must match bot)
- `DATABASE_URL_DASHBOARD` (Postgres URL with dashboard least-privilege permissions)

## Command Control Plane (Security Model)
- Dashboard writes commands into `deepstack_bot_commands`.
- Each command is HMAC-signed and has an expiry + nonce.
- Bot verifies signature + expiry + replay before executing.
- If `BOT_COMMAND_HMAC_SECRET` is missing, bot commands are rejected (safe-by-default).

## Running Migrations (Dashboard)
From `dashboard/`:
```bash
npm run db:setup
```
Test DB:
```bash
npm run test:db:setup
```

## Running Tests
Backend (repo root):
```bash
pytest
```
Dashboard:
```bash
cd dashboard
npm ci
npm test
```

## Dependency Advisories (Dashboard)
- We intentionally pin the dashboard to **Next 14** for deterministic tooling and compatibility.
- As of this branch, `npm audit` reports a high-severity advisory against some Next.js versions; the suggested `npm audit fix --force`
  upgrades to Next 16 (breaking change). We are **not** taking that upgrade in this pass.

## Running The Bot
Dry-run (default):
```bash
python run_bot.py --multi
```

Live trading (explicitly gated):
```bash
export KALSHI_LIVE_TRADING=1
python run_bot.py --multi --live
```

## launchd
- Launcher script: `scripts/bot-launcher.sh`
- launchd plist: `com.id8labs.deepstack-bot.plist`

The launcher sources the bot env from:
`~/Library/Application Support/deepstack/kalshi-trading.env` (or `DEEPSTACK_BOT_ENV_PATH`)
