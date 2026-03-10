import { NextResponse } from 'next/server';
import { restGet } from '@/lib/postgres';
import type { TvIndicator } from '@/lib/research-types';

const ALLOWED_SORT_COLUMNS = new Set([
  'composite_score', 'avg_sharpe', 'avg_roi', 'avg_win_rate',
  'avg_profit_factor', 'num_tickers_tested', 'rank', 'created_at', 'updated_at',
]);

const ALLOWED_ORDERS = new Set(['asc', 'desc']);

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const rawSort = searchParams.get('sort') || 'composite_score';
    const rawOrder = searchParams.get('order') || 'desc';
    const rawLimit = parseInt(searchParams.get('limit') || '50', 10);
    const rawOffset = parseInt(searchParams.get('offset') || '0', 10);
    const category = searchParams.get('category');

    // Whitelist validation
    const sort = ALLOWED_SORT_COLUMNS.has(rawSort) ? rawSort : 'composite_score';
    const order = ALLOWED_ORDERS.has(rawOrder) ? rawOrder : 'desc';
    const limit = Math.min(isNaN(rawLimit) ? 50 : Math.max(1, rawLimit), 200);
    const offset = isNaN(rawOffset) ? 0 : Math.max(0, rawOffset);

    // Build PostgREST query params
    const params: string[] = [
      `order=${sort}.${order}.nullslast`,
      `limit=${limit}`,
      `offset=${offset}`,
    ];

    if (category) {
      params.push(`category=eq.${encodeURIComponent(category)}`);
    }

    // Fetch with count header for total
    const indicators = await restGet<TvIndicator>(
      'ds_tv_indicators',
      params.join('&')
    );

    return NextResponse.json(
      { indicators, total: indicators.length },
      { headers: { 'Cache-Control': 'private, max-age=30' } }
    );
  } catch (error) {
    console.error('Error fetching TV indicators:', error);
    return NextResponse.json(
      { indicators: [], total: 0, error: 'Database error' },
      { status: 500 }
    );
  }
}
