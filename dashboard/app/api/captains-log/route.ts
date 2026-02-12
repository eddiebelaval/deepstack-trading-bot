import { NextRequest, NextResponse } from 'next/server';
import { getCaptainsLogEntries, createCaptainsLogEntry } from '@/lib/db-postgres';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get('limit') || '50', 10), 500);
    const after = searchParams.get('after') || undefined;

    const entries = await getCaptainsLogEntries(limit, after);
    return NextResponse.json({ entries });
  } catch (error) {
    console.error('Error fetching captains log:', error);
    return NextResponse.json(
      { error: 'Failed to fetch captains log' },
      { status: 503 },
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const message = typeof body.message === 'string' ? body.message.trim() : '';

    if (!message || message.length > 500) {
      return NextResponse.json(
        { error: 'Message required (max 500 chars)' },
        { status: 400 },
      );
    }

    const entry = await createCaptainsLogEntry(message);
    return NextResponse.json({ entry }, { status: 201 });
  } catch (error) {
    console.error('Error creating captains log entry:', error);
    return NextResponse.json(
      { error: 'Failed to create entry' },
      { status: 500 },
    );
  }
}
