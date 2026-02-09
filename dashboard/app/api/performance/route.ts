import { NextResponse } from 'next/server';
import { getBalanceHistory } from '@/lib/db-postgres';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(Number(searchParams.get('limit') || '500'), 2000);

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
