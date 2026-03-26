# Build Real-Time Trading Dashboard

## Context

This is a **private trading bot** for personal use only. The bot scans Kalshi + Polymarket markets using 3 strategies (mean-reversion, combinatorial arbitrage, cross-platform arbitrage).

**IMPORTANT:** This dashboard is for the **kalshi-trading bot**, NOT the DeepStack public repo. Do not commit or upload this to any public repository. This stays local in `./`.

---

## Design Language: Green Phosphorus Terminal

**Aesthetic:** Retro CRT monitor, Matrix-style green on black, but make it look fucking badass.

**Visual Requirements:**
- **Color scheme:** Bright green (#00FF41) on black (#0D0208)
- **Fonts:** Monospace (JetBrains Mono, Fira Code, or similar)
- **Effects:** 
  - Scanlines overlay (subtle CRT effect)
  - Glowing text (CSS text-shadow)
  - ASCII art borders/dividers
  - Blinking cursor on live feeds
- **Style:** Terminal/command-line interface aesthetic
- **Animation:** Text should stream/typewriter effect where appropriate
- **Responsive:** Desktop-first (this is for monitoring at the computer)

---

## Dashboard Sections

### 1. Header
```
╔══════════════════════════════════════════════════════════════════╗
║  DEEPSTACK TRADER                                    [LIVE] ████║
║  Multi-Strategy Arbitrage Bot                     22:45:13 EST  ║
╚══════════════════════════════════════════════════════════════════╝
```

### 2. Strategy Status (3 columns)

```
┌─ MEAN REVERSION ─────┐  ┌─ COMBINATORIAL ARB ──┐  ┌─ CROSS-PLATFORM ─────┐
│ STATUS: SCANNING     │  │ STATUS: SCANNING     │  │ STATUS: SCANNING      │
│ MARKETS: 0 INXD      │  │ MARKETS: 100 ALL     │  │ POLY: 2,510          │
│ OPPORTUNITIES: 0     │  │ OPPORTUNITIES: 0     │  │ KALSHI: 100          │
│ LAST SCAN: 2s ago    │  │ LAST SCAN: 2s ago    │  │ MATCHES: 0           │
└──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

**Data source:** Live from bot's strategy_manager

### 3. Live Market Feed (scrolling terminal)

```
┌─ LIVE FEED ───────────────────────────────────────────────────────┐
│ [22:45:01] Scanning 2,510 Polymarket markets...                  │
│ [22:45:01] Scanning 100 Kalshi markets...                        │
│ [22:45:02] [MEAN_REVERSION] No INXD markets (after hours)        │
│ [22:45:02] [COMBINATORIAL] Checking 100 markets for arb sets...  │
│ [22:45:02] [CROSS_PLATFORM] Comparing 200 Poly vs 100 Kalshi...  │
│ [22:45:03] No opportunities found                                │
│ [22:45:03] Next scan in 57s...                                   │
│ █                                                                 │
└───────────────────────────────────────────────────────────────────┘
```

**Data source:** Bot logs (tail the log file or WebSocket events)

### 4. Account & Risk Metrics (2 columns)

```
┌─ ACCOUNT ────────────┐  ┌─ RISK MANAGEMENT ─────────────────────┐
│ BALANCE: $0.00       │  │ MAX POSITION: $50                     │
│ P&L TODAY: $0.00     │  │ DAILY LOSS LIMIT: $100                │
│ P&L TOTAL: $0.00     │  │ CURRENT EXPOSURE: $0                  │
│ WIN RATE: N/A        │  │ KELLY FRACTION: 0.5 (half-Kelly)      │
└──────────────────────┘  │ EMOTIONAL FIREWALL: ACTIVE ✓          │
                          └───────────────────────────────────────┘
```

**Data source:** `trade_journal.db` + bot's risk management state

### 5. Recent Trades Table

```
┌─ TRADE JOURNAL ────────────────────────────────────────────────────────┐
│ TIME      STRATEGY        TICKER    SIDE  ENTRY   EXIT   P&L    STATUS│
├────────────────────────────────────────────────────────────────────────┤
│ (no trades yet - waiting for funding)                                 │
└────────────────────────────────────────────────────────────────────────┘
```

**Data source:** `trade_journal.db` (SQLite queries)

### 6. Footer

```
╔══════════════════════════════════════════════════════════════════╗
║  Press Ctrl+C to stop bot  |  Logs: multi_strategy.log          ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Tech Stack

**Framework:** Next.js (App Router)  
**Styling:** Tailwind CSS + custom terminal theme  
**Real-time:** Server-Sent Events (SSE) or WebSocket  
**Data:**
- Read `trade_journal.db` (SQLite)
- Tail `multi_strategy.log` for live feed
- Poll bot status via API endpoint (create simple HTTP endpoint in bot)

**File Structure:**
```
kalshi-trading/
├── dashboard/
│   ├── app/
│   │   ├── page.tsx          (main dashboard)
│   │   ├── api/
│   │   │   ├── status/route.ts    (bot status endpoint)
│   │   │   ├── trades/route.ts    (recent trades)
│   │   │   └── feed/route.ts      (live log stream)
│   │   └── layout.tsx
│   ├── components/
│   │   ├── StrategyCard.tsx
│   │   ├── LiveFeed.tsx
│   │   ├── TradeJournal.tsx
│   │   └── RiskMetrics.tsx
│   ├── lib/
│   │   ├── db.ts             (SQLite queries)
│   │   └── terminal.css      (CRT effects)
│   ├── public/
│   │   └── fonts/            (JetBrains Mono)
│   ├── package.json
│   ├── tsconfig.json
│   └── next.config.js
```

---

## API Requirements

**Create simple HTTP server in the bot** (add to `kalshi_trader/main.py`):

```python
# Add FastAPI endpoints for dashboard:
# GET /status -> current bot state, strategies, scan times
# GET /trades -> recent trades from journal
# GET /feed -> SSE stream of log events
```

Or simpler: Dashboard just reads files directly (no API needed):
- Read `trade_journal.db`
- Tail `multi_strategy.log`
- Read bot state from a JSON file the bot writes every scan

---

## Implementation Steps

1. **Create Next.js dashboard** in `./dashboard/`
2. **Design terminal theme** (green phosphorus, scanlines, CRT glow)
3. **Build components** (StrategyCard, LiveFeed, TradeJournal, etc.)
4. **Connect to data sources** (SQLite, log file, bot state)
5. **Add real-time updates** (SSE or WebSocket for live feed)
6. **Test with running bot** (make sure data flows correctly)

---

## Design Inspiration

**Visual references:**
- Matrix digital rain aesthetic
- Fallout terminal UI
- Old school IBM green screen terminals
- Hacker movie terminal interfaces

**Color palette:**
- Primary: `#00FF41` (bright terminal green)
- Background: `#0D0208` (almost black)
- Accent: `#39FF14` (neon green)
- Dim text: `#006400` (dark green for secondary info)
- Error/loss: `#FF0000` (red)
- Success/profit: `#00FF41` (bright green)

**Typography:**
- Monospace only
- Use `font-mono` from Tailwind
- Add JetBrains Mono or Fira Code for extra authenticity

---

## Important Constraints

🚨 **DO NOT:**
- Commit this to the DeepStack public repo
- Upload to any public GitHub
- Include any API keys or secrets in the code
- Connect to external services (all local data)

✅ **DO:**
- Keep everything in `./dashboard/`
- Make it look fucking badass with terminal aesthetics
- Ensure real-time updates work smoothly
- Add hover effects, animations, and polish
- Make it responsive (but desktop-first)

---

## Deliverables

1. Working Next.js dashboard at `dashboard/`
2. Terminal green phosphorus theme with CRT effects
3. Real-time data from bot (live feed, trades, status)
4. Clean component architecture
5. README with setup instructions

---

## Example Terminal CSS (starting point)

```css
/* CRT scanlines effect */
@keyframes scanlines {
  0% { background-position: 0 0; }
  100% { background-position: 0 100%; }
}

.terminal {
  background: #0D0208;
  color: #00FF41;
  font-family: 'JetBrains Mono', monospace;
  position: relative;
  overflow: hidden;
}

.terminal::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    rgba(18, 16, 16, 0) 50%,
    rgba(0, 0, 0, 0.25) 50%
  );
  background-size: 100% 4px;
  animation: scanlines 0.5s linear infinite;
  pointer-events: none;
  z-index: 10;
}

.terminal-text {
  text-shadow: 0 0 5px #00FF41, 0 0 10px #00FF41;
}

.blink {
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}
```

---

**START HERE:** Create the Next.js project in `dashboard/`, build the terminal theme, then connect to the bot's data sources.

Make it look **fucking badass** with that green phosphorus terminal aesthetic! 🟢🖥️
