import { NextRequest, NextResponse } from 'next/server';
import { verifyToken } from '@/lib/auth';

// Exact public paths (no prefix matching to prevent bypass via /login/../admin)
const PUBLIC_PATHS = new Set(['/login', '/api/auth', '/api/health']);

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
