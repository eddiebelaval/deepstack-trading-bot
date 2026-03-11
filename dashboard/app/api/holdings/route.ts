import { NextRequest, NextResponse } from 'next/server';
import { getHoldings } from '@/lib/db-postgres';

export async function GET(req: NextRequest) {
  try {
    const platform = req.nextUrl.searchParams.get('platform') ?? undefined;
    const holdings = await getHoldings(platform);
    return NextResponse.json(
      { holdings },
      { headers: { 'Cache-Control': 'private, max-age=5' } },
    );
  } catch (error) {
    console.error('Error fetching holdings:', error);
    return NextResponse.json({ holdings: [], error: 'Database error' }, { status: 500 });
  }
}
