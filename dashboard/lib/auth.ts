/**
 * Shared authentication utilities.
 *
 * Uses Web Crypto API (works in both Edge Runtime and Node.js).
 * Tokens are timestamped HMACs: HMAC-SHA256(secret, "authenticated:<epoch_seconds>")
 * Format stored in cookie: "<hex_signature>:<epoch_seconds>"
 */

const TOKEN_MAX_AGE_SECONDS = 7 * 24 * 60 * 60; // 7 days

export function getAuthSecret(): string {
  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    throw new Error('AUTH_SECRET environment variable is required');
  }
  return secret;
}

export function getDashboardPassword(): string {
  return process.env.DASHBOARD_PASSWORD || '';
}

async function hmacSign(secret: string, message: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(message));
  return Array.from(new Uint8Array(signature))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

export async function signToken(): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const payload = `authenticated:${now}`;
  const signature = await hmacSign(getAuthSecret(), payload);
  return `${signature}:${now}`;
}

export async function verifyToken(token: string): Promise<boolean> {
  try {
    const parts = token.split(':');
    if (parts.length !== 2) return false;

    const [signature, timestampStr] = parts;
    const timestamp = parseInt(timestampStr, 10);
    if (isNaN(timestamp)) return false;

    // Check expiry
    const now = Math.floor(Date.now() / 1000);
    if (now - timestamp > TOKEN_MAX_AGE_SECONDS) return false;
    if (timestamp > now + 60) return false; // reject future tokens (clock skew allowance)

    // Recompute and compare in constant time
    const expected = await hmacSign(getAuthSecret(), `authenticated:${timestamp}`);
    return timingSafeCompare(signature, expected);
  } catch {
    return false;
  }
}

/** Constant-time string comparison (Edge-compatible, no Node.js crypto needed) */
function timingSafeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

export function safeCompare(a: string, b: string): boolean {
  return timingSafeCompare(a, b);
}
