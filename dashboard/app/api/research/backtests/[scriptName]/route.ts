import { NextResponse } from 'next/server';
import { restGet } from '@/lib/postgres';
import type { TvBacktest } from '@/lib/research-types';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ scriptName: string }> }
) {
  try {
    const { scriptName } = await params;
    const backtests = await restGet<TvBacktest>(
      'ds_tv_backtests',
      `script_name=eq.${encodeURIComponent(scriptName)}&order=ticker.asc`
    );

    return NextResponse.json(
      { backtests },
      { headers: { 'Cache-Control': 'private, max-age=30' } }
    );
  } catch (error) {
    console.error('Error fetching backtests:', error);
    return NextResponse.json(
      { backtests: [], error: 'Database error' },
      { status: 500 }
    );
  }
}
