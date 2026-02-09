/**
 * Kalshi Prediction Market Hours
 *
 * Kalshi operates 24/7 with one scheduled maintenance window:
 *   Thursday 3:00 AM – 5:00 AM Eastern Time
 *
 * Source: https://help.kalshi.com/trading/what-are-trading-hours
 */

export type MarketState = 'open' | 'pre_market' | 'after_hours' | 'closed';

interface MarketStatus {
  state: MarketState;
  label: string;
  nextChange: string;
}

const MAINTENANCE_DAY = 4; // Thursday (0=Sun, 4=Thu)
const MAINTENANCE_START = 3 * 60; // 3:00 AM ET in minutes
const MAINTENANCE_END = 5 * 60;   // 5:00 AM ET in minutes

/**
 * Get current Eastern Time using Intl.DateTimeFormat for reliable
 * timezone conversion (no string round-trip parsing).
 */
function getETComponents(now?: Date): { day: number; hours: number; minutes: number } {
  const date = now ?? new Date();

  // Use Intl.DateTimeFormat to extract individual components — avoids
  // the fragile toLocaleString → new Date() round-trip that broke before
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: 'numeric',
    minute: 'numeric',
    weekday: 'short',
    hour12: false,
  });

  const parts = fmt.formatToParts(date);
  const dayStr = parts.find(p => p.type === 'weekday')?.value ?? '';
  const hours = parseInt(parts.find(p => p.type === 'hour')?.value ?? '0', 10);
  const mins = parseInt(parts.find(p => p.type === 'minute')?.value ?? '0', 10);

  const dayMap: Record<string, number> = {
    Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6,
  };

  return {
    day: dayMap[dayStr] ?? new Date().getDay(),
    hours,
    minutes: mins,
  };
}

function formatDuration(minutes: number): string {
  if (minutes < 0) minutes = 0;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

export function getMarketStatus(now?: Date): MarketStatus {
  const { day, hours, minutes } = getETComponents(now);
  const minutesSinceMidnight = hours * 60 + minutes;

  // Check if we're in the Thursday maintenance window
  if (day === MAINTENANCE_DAY &&
      minutesSinceMidnight >= MAINTENANCE_START &&
      minutesSinceMidnight < MAINTENANCE_END) {
    return {
      state: 'closed',
      label: 'MAINTENANCE',
      nextChange: `opens in ${formatDuration(MAINTENANCE_END - minutesSinceMidnight)}`,
    };
  }

  // Calculate time until next maintenance window
  let daysUntilThursday = (MAINTENANCE_DAY - day + 7) % 7;
  if (daysUntilThursday === 0 && minutesSinceMidnight >= MAINTENANCE_END) {
    daysUntilThursday = 7; // Already past this week's maintenance
  }

  const minutesUntilMaintenance =
    daysUntilThursday === 0
      ? MAINTENANCE_START - minutesSinceMidnight
      : (daysUntilThursday - 1) * 24 * 60 + (24 * 60 - minutesSinceMidnight) + MAINTENANCE_START;

  return {
    state: 'open',
    label: 'MARKET OPEN',
    nextChange: `maintenance in ${formatDuration(minutesUntilMaintenance)}`,
  };
}
