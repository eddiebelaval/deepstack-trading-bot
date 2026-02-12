import { NextRequest, NextResponse } from 'next/server';
import { getAuthSecret, getDashboardPassword, signToken, safeCompare } from '@/lib/auth';

// In-memory sliding window rate limiter (resets on cold start, acceptable for serverless)
const RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000; // 15 minutes
const RATE_LIMIT_MAX_ATTEMPTS = 5;
const rateLimitMap = new Map<string, { count: number; windowStart: number }>();

function getClientIp(request: NextRequest): string {
  return request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown';
}

function checkRateLimit(ip: string): { allowed: boolean; retryAfterSeconds: number } {
  const now = Date.now();
  const entry = rateLimitMap.get(ip);

  if (!entry || now - entry.windowStart > RATE_LIMIT_WINDOW_MS) {
    rateLimitMap.set(ip, { count: 1, windowStart: now });
    return { allowed: true, retryAfterSeconds: 0 };
  }

  if (entry.count >= RATE_LIMIT_MAX_ATTEMPTS) {
    const retryAfterSeconds = Math.ceil((entry.windowStart + RATE_LIMIT_WINDOW_MS - now) / 1000);
    return { allowed: false, retryAfterSeconds };
  }

  entry.count++;
  return { allowed: true, retryAfterSeconds: 0 };
}

export async function POST(request: NextRequest) {
  const ip = getClientIp(request);
  const rateCheck = checkRateLimit(ip);

  if (!rateCheck.allowed) {
    return NextResponse.json(
      { error: 'Too many login attempts. Try again later.' },
      {
        status: 429,
        headers: { 'Retry-After': String(rateCheck.retryAfterSeconds) },
      }
    );
  }

  try {
    // Fail fast if secret is not configured
    getAuthSecret();

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

    const token = await signToken();

    const response = NextResponse.json({ success: true });
    response.cookies.set('deepstack_auth', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      path: '/',
      maxAge: 60 * 60 * 24 * 7, // 7 days
    });

    return response;
  } catch (error) {
    if (error instanceof Error && error.message.includes('AUTH_SECRET')) {
      console.error('Auth misconfiguration:', error.message);
      return NextResponse.json({ error: 'Server configuration error' }, { status: 500 });
    }
    return NextResponse.json({ error: 'Invalid request' }, { status: 400 });
  }
}

export async function DELETE(request: NextRequest) {
  // Verify the user is actually authenticated before allowing logout
  const authToken = request.cookies.get('deepstack_auth')?.value;
  if (!authToken) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const response = NextResponse.json({ success: true });
  response.cookies.delete('deepstack_auth');
  return response;
}
