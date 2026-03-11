import { NextRequest, NextResponse } from 'next/server';
import { verifyToken } from '@/lib/auth';

// Exact public paths (no prefix matching to prevent bypass via /login/../admin)
const PUBLIC_PATHS = new Set(['/login', '/api/auth', '/api/health']);

// IP whitelist — bypass auth for Eddie's home network.
// Env var overrides hardcoded list. Comma-separated IPs.
// Password login still works as fallback for remote access.
const WHITELISTED_IPS = new Set(
  (process.env.WHITELISTED_IPS || '73.205.31.126').split(',').map((ip) => ip.trim()),
);

function getClientIp(request: NextRequest): string {
  // Vercel sets x-forwarded-for; first entry is the real client IP
  const forwarded = request.headers.get('x-forwarded-for');
  if (forwarded) return forwarded.split(',')[0].trim();
  // Fallback for local dev
  return request.headers.get('x-real-ip') || '127.0.0.1';
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow static assets
  if (pathname.startsWith('/_next') || pathname.startsWith('/favicon')) {
    return NextResponse.next();
  }

  // Allow exact public paths
  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  // IP whitelist — skip auth entirely for trusted IPs
  const clientIp = getClientIp(request);
  if (WHITELISTED_IPS.has(clientIp)) {
    const response = NextResponse.next();
    response.headers.set('X-Content-Type-Options', 'nosniff');
    response.headers.set('X-Frame-Options', 'DENY');
    response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
    return response;
  }

  // Check for auth cookie
  const authToken = request.cookies.get('deepstack_auth')?.value;
  if (!authToken) {
    return redirectToLogin(request, pathname);
  }

  // Verify the token HMAC signature and expiry
  if (!(await verifyToken(authToken))) {
    const response = redirectToLogin(request, pathname);
    response.cookies.delete('deepstack_auth');
    return response;
  }

  // CSRF protection: mutation requests to API must include custom header
  // Browsers won't send custom headers on cross-origin form submissions
  if (pathname.startsWith('/api/') && ['POST', 'PATCH', 'PUT', 'DELETE'].includes(request.method)) {
    const hasCustomHeader = request.headers.get('content-type')?.includes('application/json');
    if (!hasCustomHeader) {
      return NextResponse.json({ error: 'Invalid content type' }, { status: 415 });
    }
  }

  // Add security headers
  const response = NextResponse.next();
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  return response;
}

function redirectToLogin(request: NextRequest, from: string): NextResponse {
  const loginUrl = new URL('/login', request.url);
  // Only allow relative paths to prevent open redirect
  if (from.startsWith('/') && !from.startsWith('//')) {
    loginUrl.searchParams.set('from', from);
  }
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
