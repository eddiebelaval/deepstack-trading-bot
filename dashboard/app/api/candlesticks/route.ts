import { NextResponse } from 'next/server';
import { Candlestick } from '@/lib/types';

const KALSHI_BASE = 'https://api.elections.kalshi.com/trade-api/v2';

/**
 * Proxy to Kalshi public candlestick API.
 * No auth required — market data is public.
 *
 * Query params:
 *   ticker (required) — market ticker, e.g. KXBTC-26FEB0912-B79125
 *   series (required) — series ticker, e.g. KXBTC
 *   period (optional) — 1 | 60 | 1440 (minutes). Default: 60
 *   hours (optional) — lookback window in hours. Default: 24
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const ticker = searchParams.get('ticker');
    const series = searchParams.get('series');
    const rawPeriod = parseInt(searchParams.get('period') || '60', 10);
    const rawHours = parseInt(searchParams.get('hours') || '24', 10);
    const period = [1, 60, 1440].includes(rawPeriod) ? rawPeriod : 60;
    const hours = Math.min(isNaN(rawHours) ? 24 : Math.max(1, rawHours), 720);

    if (!ticker || !series) {
      return NextResponse.json(
        { error: 'ticker and series params required' },
        { status: 400 }
      );
    }

    const endTs = Math.floor(Date.now() / 1000);
    const startTs = endTs - hours * 3600;

    const url = `${KALSHI_BASE}/series/${series}/markets/${ticker}/candlesticks?period_interval=${period}&start_ts=${startTs}&end_ts=${endTs}`;

    const resp = await fetch(url, {
      next: { revalidate: 30 },
    });

    if (!resp.ok) {
      return NextResponse.json(
        { candlesticks: [], error: `Kalshi returned ${resp.status}` },
        { status: 502 }
      );
    }

    const data = await resp.json();
    const raw = data.candlesticks || [];

    const candlesticks: Candlestick[] = raw.map((c: Record<string, unknown>) => {
      const price = (c.price && typeof c.price === 'object') ? c.price as Record<string, number> : {};
      return {
        end_period_ts: typeof c.end_period_ts === 'number' ? c.end_period_ts : 0,
        open: typeof price.open === 'number' ? price.open : 0,
        high: typeof price.high === 'number' ? price.high : 0,
        low: typeof price.low === 'number' ? price.low : 0,
        close: typeof price.close === 'number' ? price.close : 0,
        volume: typeof c.volume === 'number' ? c.volume : 0,
        open_interest: typeof c.open_interest === 'number' ? c.open_interest : 0,
      };
    });

    return NextResponse.json(
      { candlesticks },
      { headers: { 'Cache-Control': 'private, max-age=30' } }
    );
  } catch (error) {
    console.error('Candlestick fetch error:', error);
    return NextResponse.json({ candlesticks: [], error: 'Fetch failed' }, { status: 500 });
  }
}
