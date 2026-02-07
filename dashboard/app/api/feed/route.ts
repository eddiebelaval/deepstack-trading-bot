import { NextResponse } from 'next/server';
import { getRecentLogs, createLogEntry } from '@/lib/db-postgres';
import { LogEntry } from '@/lib/types';

export async function GET() {
  try {
    const logs = await getRecentLogs(50);
    return NextResponse.json({ logs });
  } catch (error) {
    console.error('Error fetching logs:', error);
    return NextResponse.json({ logs: [] });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const entry: Omit<LogEntry, 'id'> = {
      timestamp: body.timestamp || new Date().toISOString(),
      level: body.level || 'INFO',
      strategy: body.strategy || null,
      message: body.message,
    };
    await createLogEntry(entry);
    return NextResponse.json({ success: true }, { status: 201 });
  } catch (error) {
    console.error('Error creating log entry:', error);
    return NextResponse.json({ error: 'Failed to create log entry' }, { status: 500 });
  }
}
