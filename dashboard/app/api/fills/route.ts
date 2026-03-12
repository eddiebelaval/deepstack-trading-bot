import { NextResponse } from 'next/server';
import { getFills } from '@/lib/db-postgres';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(Number(searchParams.get('limit') || '20'), 50);
    const fills = await getFills(limit);
    return NextResponse.json(
      { fills },
      { headers: { 'Cache-Control': 'private, max-age=5' } },
    );
  } catch (error) {
    console.error('Error fetching fills:', error);
    return NextResponse.json({ fills: [], error: 'Database error' }, { status: 500 });
  }
}
