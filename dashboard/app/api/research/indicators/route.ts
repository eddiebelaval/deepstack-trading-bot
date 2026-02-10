import { NextResponse } from 'next/server';
import { restGet } from '@/lib/postgres';
import type { TvIndicator } from '@/lib/research-types';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const sort = searchParams.get('sort') || 'composite_score';
    const order = searchParams.get('order') || 'desc';
    const limit = searchParams.get('limit') || '50';
    const offset = searchParams.get('offset') || '0';
    const category = searchParams.get('category');

    // Build PostgREST query params
    const params: string[] = [
      `order=${sort}.${order}.nullslast`,
      `limit=${limit}`,
      `offset=${offset}`,
    ];

    if (category) {
      params.push(`category=eq.${category}`);
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
