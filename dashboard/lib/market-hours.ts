/**
 * US Stock Market Hours (NYSE/NASDAQ)
 * All times Eastern Time.
 */

export type MarketState = 'open' | 'pre_market' | 'after_hours' | 'closed';

interface MarketStatus {
  state: MarketState;
  label: string;
  nextChange: string; // e.g. "opens in 15h 30m"
}

const ET_TIMEZONE = 'America/New_York';

// Minutes from midnight ET
const PRE_MARKET_OPEN = 4 * 60;        // 4:00 AM
const MARKET_OPEN = 9 * 60 + 30;       // 9:30 AM
const MARKET_CLOSE = 16 * 60;          // 4:00 PM
const AFTER_HOURS_CLOSE = 20 * 60;     // 8:00 PM

function getETTime(now?: Date): { day: number; minutes: number; date: Date } {
  const date = now ?? new Date();
  const etStr = date.toLocaleString('en-US', { timeZone: ET_TIMEZONE });
  const et = new Date(etStr);
  return {
    day: et.getDay(), // 0=Sun, 6=Sat
    minutes: et.getHours() * 60 + et.getMinutes(),
    date: et,
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
  const { day, minutes } = getETTime(now);
  const isWeekday = day >= 1 && day <= 5;

  if (!isWeekday) {
    // Weekend — calculate time until Monday 4:00 AM pre-market
    const daysUntilMonday = day === 0 ? 1 : (8 - day); // Sat=2, Sun=1
    const minutesUntilPreMarket =
      (daysUntilMonday - 1) * 24 * 60 + (24 * 60 - minutes) + PRE_MARKET_OPEN;
    return {
      state: 'closed',
      label: 'MARKET CLOSED',
      nextChange: `pre-market in ${formatDuration(minutesUntilPreMarket)}`,
    };
  }

  // Weekday
  if (minutes >= MARKET_OPEN && minutes < MARKET_CLOSE) {
    return {
      state: 'open',
      label: 'MARKET OPEN',
      nextChange: `closes in ${formatDuration(MARKET_CLOSE - minutes)}`,
    };
  }

  if (minutes >= PRE_MARKET_OPEN && minutes < MARKET_OPEN) {
    return {
      state: 'pre_market',
      label: 'PRE-MARKET',
      nextChange: `opens in ${formatDuration(MARKET_OPEN - minutes)}`,
    };
  }

  if (minutes >= MARKET_CLOSE && minutes < AFTER_HOURS_CLOSE) {
    return {
      state: 'after_hours',
      label: 'AFTER HOURS',
      nextChange: `closes in ${formatDuration(AFTER_HOURS_CLOSE - minutes)}`,
    };
  }

  // Before pre-market (midnight to 4 AM) or after after-hours (8 PM to midnight)
  if (minutes < PRE_MARKET_OPEN) {
    return {
      state: 'closed',
      label: 'MARKET CLOSED',
      nextChange: `pre-market in ${formatDuration(PRE_MARKET_OPEN - minutes)}`,
    };
  }

  // After 8 PM — next session depends on day
  if (day === 5) {
    // Friday evening — next is Monday
    const minutesUntilMonday = (2 * 24 * 60) + (24 * 60 - minutes) + PRE_MARKET_OPEN;
    return {
      state: 'closed',
      label: 'MARKET CLOSED',
      nextChange: `pre-market in ${formatDuration(minutesUntilMonday)}`,
    };
  }

  return {
    state: 'closed',
    label: 'MARKET CLOSED',
    nextChange: `pre-market in ${formatDuration(24 * 60 - minutes + PRE_MARKET_OPEN)}`,
  };
}
