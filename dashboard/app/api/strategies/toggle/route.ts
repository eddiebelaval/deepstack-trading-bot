import { NextRequest, NextResponse } from 'next/server';
import { updateStrategyStatus } from '@/lib/db-postgres';

export async function POST(request: NextRequest) {
  try {
    const { strategy, enabled } = await request.json();

    if (!strategy || typeof enabled !== 'boolean') {
      return NextResponse.json(
        { error: 'Missing strategy name or enabled boolean' },
        { status: 400 }
      );
    }

    const result = await updateStrategyStatus(strategy, { enabled });

    if (!result) {
      return NextResponse.json(
        { error: `Strategy '${strategy}' not found` },
        { status: 404 }
      );
    }

    return NextResponse.json({ success: true, strategy: result });
  } catch (error) {
    console.error('Failed to toggle strategy:', error);
    return NextResponse.json(
      { error: 'Failed to toggle strategy' },
      { status: 500 }
    );
  }
}
