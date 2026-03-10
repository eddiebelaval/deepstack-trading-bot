import { NextRequest, NextResponse } from 'next/server';
import { getChatMessages, createChatMessage } from '@/lib/db-postgres';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const limit = Math.min(
      parseInt(searchParams.get('limit') || '100', 10),
      500,
    );
    const after = searchParams.get('after') || undefined;

    const messages = await getChatMessages(limit, after);
    return NextResponse.json(
      { messages },
      { headers: { 'Cache-Control': 'private, max-age=3' } },
    );
  } catch (error) {
    console.error('Error fetching chat messages:', error);
    return NextResponse.json({ messages: [] }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const content = typeof body.content === 'string' ? body.content.trim() : '';

    if (!content || content.length > 2000) {
      return NextResponse.json(
        { error: 'Message required (max 2000 chars)' },
        { status: 400 },
      );
    }

    const message = await createChatMessage(content, 'dashboard', 'user');
    return NextResponse.json({ message }, { status: 201 });
  } catch (error) {
    console.error('Error creating chat message:', error);
    return NextResponse.json(
      { error: 'Failed to send message' },
      { status: 500 },
    );
  }
}
