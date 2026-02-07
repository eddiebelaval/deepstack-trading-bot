import { NextResponse } from 'next/server';
import { getRecentLogs, createLogEntry } from '@/lib/db-postgres';
import { CreateLogEntrySchema, validateRequest } from '@/lib/validation';

export async function GET() {
  try {
    const logs = await getRecentLogs(50);
    return NextResponse.json({ logs });
  } catch (error) {
    console.error('Error fetching logs:', error);
    return NextResponse.json(
      { error: 'Failed to fetch logs' },
      { status: 503 }
    );
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const validation = validateRequest(CreateLogEntrySchema, body);

    if (!validation.success) {
      return NextResponse.json({ error: validation.error }, { status: 400 });
    }

    const { level, strategy, message, timestamp } = validation.data;
    await createLogEntry({
      timestamp: timestamp || new Date().toISOString(),
      level: level as 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG',
      strategy: strategy ?? null,
      message,
    });
    return NextResponse.json({ success: true }, { status: 201 });
  } catch (error) {
    console.error('Error creating log entry:', error);
    return NextResponse.json({ error: 'Failed to create log entry' }, { status: 500 });
  }
}
