import { NextRequest, NextResponse } from 'next/server';
import { getBalanceHistory } from '@/lib/db-postgres';

// This route reads request search params and hits the database, so it must be dynamic.
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    // Keep this endpoint flexible: charts may need more history than 2,000 rows.
    // Still cap to prevent accidentally returning an unbounded dataset.
    const limit = Math.min(Number(searchParams.get('limit') || '500'), 5000);

    const history = await getBalanceHistory(limit);

    return NextResponse.json(
      { history },
      { headers: { 'Cache-Control': 'private, max-age=30' } }
    );
  } catch (error) {
    console.error('Error fetching balance history:', error);
    return NextResponse.json({ history: [] }, { status: 500 });
  }
}
