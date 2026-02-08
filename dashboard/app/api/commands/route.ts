import { NextResponse } from 'next/server';
import { createCommand, getRecentCommands } from '@/lib/db-postgres';
import { CreateBotCommandSchema, validateRequest } from '@/lib/validation';

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const validation = validateRequest(CreateBotCommandSchema, body);

    if (!validation.success) {
      return NextResponse.json({ error: validation.error }, { status: 400 });
    }

    const { command, params } = validation.data;
    const result = await createCommand(command, params);

    return NextResponse.json({ command: result }, { status: 201 });
  } catch (error) {
    console.error('Failed to create command:', error);
    return NextResponse.json({ error: 'Failed to create command' }, { status: 500 });
  }
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get('limit') || '20', 10), 100);

    const commands = await getRecentCommands(limit);
    return NextResponse.json({ commands });
  } catch (error) {
    console.error('Failed to fetch commands:', error);
    return NextResponse.json({ error: 'Failed to fetch commands' }, { status: 500 });
  }
}
