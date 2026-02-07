# DEEPSTACK TRADER Dashboard - Quick Start

## Installation & Running

```bash
# From the kalshi-trading/dashboard directory
cd /Users/eddiebelaval/clawd/projects/kalshi-trading/dashboard

# Install dependencies (already done)
npm install

# Start development server
npm run dev
```

**Dashboard URL:** http://localhost:3000

## What You Get

A badass CRT terminal-style dashboard with:

### Visual Features
- Green phosphorus (#00FF41) on black (#0D0208)
- CRT scanlines effect
- Glowing text shadows
- Blinking cursor in live feed
- ASCII box-drawing borders
- JetBrains Mono font

### Dashboard Sections

1. **Header**
   - DEEPSTACK TRADER v2.0 logo
   - [LIVE] status indicator (blinking)
   - Real-time clock

2. **Strategy Cards** (3 columns)
   - mean_reversion
   - combinatorial_arbitrage
   - cross_platform_arbitrage
   - Shows: status, positions, opportunities, last scan

3. **Account Metrics**
   - Balance with glow effect
   - Daily P/L (green for profit, red for loss)
   - Total positions
   - Available balance

4. **Risk Metrics**
   - Daily loss limit with progress bar
   - Kelly fraction
   - Max position size
   - Positions at risk

5. **Live Feed**
   - Scrolling terminal output
   - Parses multi_strategy.log
   - Shows timestamp, level, strategy, message
   - Auto-scrolls to bottom
   - Blinking cursor

6. **Trade Journal**
   - Recent trades table
   - Shows: time, ticker, strategy, side, size, entry, exit, P/L, status
   - Color-coded P/L (green/red)

### Auto-Refresh

Everything updates every 5 seconds automatically.

## Data Sources

The dashboard reads from:

1. **../trade_journal.db** - SQLite database with trades
2. **../multi_strategy.log** - Live bot logs
3. **../dashboard_state.json** (optional) - Bot state snapshot

## API Endpoints

- `GET /api/status` - Strategy status and metrics
- `GET /api/trades` - Recent trades from database
- `GET /api/feed` - Last 50 log entries

## File Structure

```
dashboard/
├── app/
│   ├── page.tsx              # Main dashboard (client component)
│   ├── layout.tsx            # Root layout
│   ├── globals.css           # CRT terminal CSS
│   └── api/
│       ├── status/route.ts   # Dashboard state API
│       ├── trades/route.ts   # Trades API
│       └── feed/route.ts     # Logs API
├── components/
│   ├── Header.tsx            # Header with clock
│   ├── StrategyCard.tsx      # Strategy status card
│   ├── LiveFeed.tsx          # Scrolling logs
│   ├── AccountMetrics.tsx    # Balance & P/L
│   ├── RiskMetrics.tsx       # Risk limits
│   └── TradeJournal.tsx      # Trades table
└── lib/
    ├── db.ts                 # SQLite queries
    └── types.ts              # TypeScript interfaces
```

## Customization

### Change Colors

Edit `tailwind.config.ts`:

```typescript
colors: {
  terminal: {
    black: "#0D0208",
    green: "#00FF41",
    "green-dim": "#00AA2B",
  },
}
```

### Change Update Frequency

Edit `app/page.tsx`:

```typescript
// Line 53-56
const interval = setInterval(() => {
  fetchStatus();
  fetchTrades();
}, 5000); // Change this (milliseconds)
```

### Change Max Logs

Edit `app/api/feed/route.ts`:

```typescript
// Line 54
const lines = readLastLines(logPath, 100); // Change max lines
```

## Production Deployment

```bash
# Build for production
npm run build

# Start production server
npm start
```

Or deploy to Vercel:

```bash
vercel deploy
```

## Troubleshooting

### Database errors

Make sure `trade_journal.db` exists:
```bash
ls -la ../trade_journal.db
```

### No logs showing

Check log file exists and has content:
```bash
tail ../multi_strategy.log
```

### Port 3000 in use

```bash
PORT=3001 npm run dev
```

## Next Steps

1. Run your trading bot in another terminal
2. Watch the dashboard update in real-time
3. Customize colors/layout to your preference
4. Add more metrics as needed

## Tech Stack

- Next.js 14 (App Router)
- React 18
- TypeScript
- Tailwind CSS
- better-sqlite3

Enjoy your badass CRT terminal dashboard!
