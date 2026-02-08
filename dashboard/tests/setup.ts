// Global test setup
// Each test file manages its own database pool connection
// This file just ensures environment variables are set correctly

// Use test database
process.env.PGDATABASE = 'kalshi_trading_test';
process.env.DATABASE_URL = 'postgresql://localhost:5432/kalshi_trading_test';
process.env.DATABASE_URL_DASHBOARD = process.env.DATABASE_URL;

// Commands must be signed in the new control plane.
process.env.BOT_COMMAND_HMAC_SECRET = process.env.BOT_COMMAND_HMAC_SECRET || 'test_hmac_secret';
