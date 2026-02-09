import { NextResponse } from 'next/server';
import { getPositions } from '@/lib/db-postgres';

export async function GET() {
  try {
    const positions = await getPositions();
    return NextResponse.json(
      { positions },
      { headers: { 'Cache-Control': 'private, max-age=5' } }
    );
  } catch (error) {
    console.error('Error fetching positions:', error);
    return NextResponse.json({ positions: [], error: 'Database error' }, { status: 500 });
  }
}
