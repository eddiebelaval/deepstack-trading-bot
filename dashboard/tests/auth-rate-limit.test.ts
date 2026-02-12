/**
 * Tests for auth endpoint rate limiting.
 *
 * Covers:
 * - Normal login attempts within rate limit window
 * - Brute force detection (6th attempt blocked with 429)
 * - Rate limit response includes Retry-After header
 * - Different IPs get independent rate limits
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

// We test the rate limiting logic directly by importing the route handler.
// The rate limiter uses module-level state, so we need dynamic imports
// to reset between test groups.

describe('Auth Rate Limiting', () => {
  // Mock the auth lib to avoid needing real secrets
  beforeEach(() => {
    vi.stubEnv('AUTH_SECRET', 'test-secret-that-is-at-least-32-characters-long');
    vi.stubEnv('DASHBOARD_PASSWORD', 'test-password');
  });

  function makeRequest(ip: string, password: string) {
    const headers = new Headers({
      'content-type': 'application/json',
      'x-forwarded-for': ip,
    });

    return new Request('http://localhost:3000/api/auth', {
      method: 'POST',
      headers,
      body: JSON.stringify({ password }),
    });
  }

  it('allows normal login attempts', async () => {
    // Dynamic import to get fresh module state
    const { POST } = await import('@/app/api/auth/route');

    const request = makeRequest('10.0.0.1', 'wrong-password');
    // @ts-expect-error - NextRequest type mismatch in test
    const response = await POST(request);
    // Should get 401 (wrong password), NOT 429 (rate limited)
    expect(response.status).toBe(401);
  });

  it('blocks after max attempts with 429', async () => {
    const { POST } = await import('@/app/api/auth/route');

    // Send 5 bad attempts from same IP
    for (let i = 0; i < 5; i++) {
      const req = makeRequest('10.0.0.99', 'wrong');
      // @ts-expect-error - NextRequest type mismatch in test
      await POST(req);
    }

    // 6th attempt should be blocked
    const blockedReq = makeRequest('10.0.0.99', 'wrong');
    // @ts-expect-error - NextRequest type mismatch in test
    const response = await POST(blockedReq);
    expect(response.status).toBe(429);

    const body = await response.json();
    expect(body.error).toContain('Too many');
  });

  it('includes Retry-After header on 429', async () => {
    const { POST } = await import('@/app/api/auth/route');

    // Exhaust rate limit from a unique IP
    for (let i = 0; i < 5; i++) {
      const req = makeRequest('10.0.0.88', 'wrong');
      // @ts-expect-error - NextRequest type mismatch in test
      await POST(req);
    }

    const blockedReq = makeRequest('10.0.0.88', 'wrong');
    // @ts-expect-error - NextRequest type mismatch in test
    const response = await POST(blockedReq);
    expect(response.status).toBe(429);

    const retryAfter = response.headers.get('Retry-After');
    expect(retryAfter).toBeTruthy();
    expect(Number(retryAfter)).toBeGreaterThan(0);
  });

  it('different IPs have independent rate limits', async () => {
    const { POST } = await import('@/app/api/auth/route');

    // Exhaust rate limit for IP A
    for (let i = 0; i < 5; i++) {
      const req = makeRequest('10.0.0.77', 'wrong');
      // @ts-expect-error - NextRequest type mismatch in test
      await POST(req);
    }

    // IP B should still be allowed
    const reqB = makeRequest('10.0.0.78', 'wrong');
    // @ts-expect-error - NextRequest type mismatch in test
    const responseB = await POST(reqB);
    expect(responseB.status).not.toBe(429);
  });
});
