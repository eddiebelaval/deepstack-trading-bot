import { NextResponse } from 'next/server';
import { getSettlements } from '@/lib/db-postgres';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get('limit') || '100', 10), 500);
    const settlements = await getSettlements(limit);
    return NextResponse.json(
      { settlements },
      { headers: { 'Cache-Control': 'private, max-age=5' } }
    );
  } catch (error) {
    console.error('Error fetching settlements:', error);
    return NextResponse.json({ settlements: [], error: 'Database error' }, { status: 500 });
  }
}
