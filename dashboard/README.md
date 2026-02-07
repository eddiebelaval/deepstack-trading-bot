# DEEPSTACK TRADER v2.0 - CRT Terminal Dashboard

A real-time trading dashboard with a green phosphorus CRT terminal aesthetic for the Kalshi multi-strategy trading bot.

## Features

- **Green Phosphorus CRT Aesthetic** - Matrix-style terminal with scanlines, glow effects, and blinking cursor
- **Real-time Updates** - Auto-refreshes every 5 seconds
- **Strategy Status Cards** - Monitor all active strategies (mean_reversion, combinatorial_arbitrage, cross_platform_arbitrage)
- **Live Feed** - Streaming logs from the trading bot
- **Account & Risk Metrics** - Track balance, P/L, positions, and risk limits
- **Trade Journal** - Recent trades from SQLite database

## Tech Stack

- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS
- better-sqlite3 (for database access)

## Setup

### Prerequisites

- Node.js 18+
- npm or yarn
- Trading bot running with `trade_journal.db` and `multi_strategy.log`

### Installation

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Production Build

```bash
# Build for production
npm run build

# Start production server
npm start
```

## File Structure

```
dashboard/
├── app/
│   ├── page.tsx              # Main dashboard page
│   ├── layout.tsx            # Root layout
│   ├── globals.css           # CRT effects and terminal styles
│   └── api/
│       ├── status/route.ts   # Strategy status endpoint
│       ├── trades/route.ts   # Trades endpoint
│       └── feed/route.ts     # Live logs endpoint
├── components/
│   ├── Header.tsx            # Header with LIVE indicator
│   ├── StrategyCard.tsx      # Strategy status card
│   ├── LiveFeed.tsx          # Scrolling log feed
│   ├── AccountMetrics.tsx    # Balance and P/L
│   ├── RiskMetrics.tsx       # Risk management metrics
│   └── TradeJournal.tsx      # Recent trades table
├── lib/
│   ├── db.ts                 # SQLite queries
│   └── types.ts              # TypeScript interfaces
├── package.json
├── tailwind.config.ts        # Terminal theme config
└── tsconfig.json
```

## Data Sources

The dashboard reads data from:

1. **trade_journal.db** (SQLite) - Located in parent directory
   - Trades table
   - Daily summary table

2. **multi_strategy.log** - Located in parent directory
   - Real-time bot logs
   - Strategy activity

3. **dashboard_state.json** (optional) - Written by bot
   - Strategy status
   - Account metrics
   - Risk metrics

## API Endpoints

### GET /api/status
Returns dashboard state including:
- Account metrics (balance, P/L, positions)
- Risk metrics (limits, exposure)
- Strategy status for all enabled strategies

### GET /api/trades
Returns recent trades from SQLite database.

### GET /api/feed
Returns last 50 log entries from multi_strategy.log.

## CRT Terminal Effects

The dashboard includes authentic CRT terminal effects:

- **Scanlines** - Horizontal lines overlay
- **Text Glow** - Green phosphorus glow on text
- **Blinking Cursor** - Animated cursor in live feed
- **Flickering** - Subtle screen flicker
- **Animated Scanline** - Moving scanline effect

All effects are pure CSS for performance.

## Customization

### Colors

Edit `tailwind.config.ts` to customize terminal colors:

```typescript
colors: {
  terminal: {
    black: "#0D0208",      // Background
    green: "#00FF41",      // Primary text
    "green-dim": "#00AA2B", // Dim text
  },
}
```

### Update Frequency

Edit `app/page.tsx` to change auto-refresh interval:

```typescript
// Default: 5000ms (5 seconds)
const interval = setInterval(() => {
  fetchStatus();
  fetchTrades();
}, 5000);
```

### Log Parsing

Edit `app/api/feed/route.ts` to customize log parsing for your log format.

## ASCII Art

The dashboard uses box-drawing characters for borders:

- `╔` `═` `╗` - Top border
- `╚` `═` `╝` - Bottom border
- `│` - Vertical border

## Performance

- Server-side rendering disabled for real-time updates
- Auto-refresh uses interval polling (not WebSockets)
- Database queries use read-only mode
- Logs are parsed on-demand

## Troubleshooting

### Database not found

Ensure `trade_journal.db` exists in the parent directory:

```bash
ls ../trade_journal.db
```

### No logs showing

Check that `multi_strategy.log` exists and is being written:

```bash
tail -f ../multi_strategy.log
```

### Port already in use

Change the port:

```bash
PORT=3001 npm run dev
```

## Development

```bash
# Run dev server with auto-reload
npm run dev

# Type check
npm run build

# Lint (if ESLint enabled)
npm run lint
```

## Credits

Built for the Kalshi multi-strategy trading bot.
CRT terminal aesthetic inspired by classic terminals and The Matrix.

## License

MIT
