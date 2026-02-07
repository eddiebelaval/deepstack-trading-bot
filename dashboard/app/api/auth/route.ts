import { NextRequest, NextResponse } from 'next/server';
import { createHmac, timingSafeEqual } from 'crypto';

function getAuthSecret(): string {
  return process.env.AUTH_SECRET || 'deepstack-dev-secret-change-in-production';
}

function getDashboardPassword(): string {
  return process.env.DASHBOARD_PASSWORD || '';
}

function signToken(payload: string): string {
  return createHmac('sha256', getAuthSecret()).update(payload).digest('hex');
}

function safeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  return timingSafeEqual(Buffer.from(a), Buffer.from(b));
}

export async function POST(request: NextRequest) {
  try {
    const { password } = await request.json();
    const expectedPassword = getDashboardPassword();

    if (!expectedPassword) {
      return NextResponse.json(
        { error: 'Dashboard password not configured' },
        { status: 500 }
      );
    }

    if (!password || !safeCompare(password, expectedPassword)) {
      return NextResponse.json(
        { error: 'Invalid password' },
        { status: 401 }
      );
    }

    // Create a signed token
    const token = signToken('authenticated');

    const response = NextResponse.json({ success: true });
    response.cookies.set('deepstack_auth', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      path: '/',
      maxAge: 60 * 60 * 24 * 7, // 7 days
    });

    return response;
  } catch {
    return NextResponse.json({ error: 'Invalid request' }, { status: 400 });
  }
}

export async function DELETE() {
  const response = NextResponse.json({ success: true });
  response.cookies.delete('deepstack_auth');
  return response;
}
