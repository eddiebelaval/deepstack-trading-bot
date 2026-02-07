// Supabase REST API client
// Replaces direct pg connections with PostgREST API calls.
// Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars.

const SUPABASE_URL = () => process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const SUPABASE_KEY = () => process.env.SUPABASE_SERVICE_ROLE_KEY || '';

function restUrl(table: string): string {
  return `${SUPABASE_URL()}/rest/v1/${table}`;
}

function headers(): Record<string, string> {
  const key = SUPABASE_KEY();
  return {
    'apikey': key,
    'Authorization': `Bearer ${key}`,
    'Content-Type': 'application/json',
    'Prefer': 'return=representation',
  };
}

// Generic GET with query params
export async function restGet<T>(table: string, params: string = ''): Promise<T[]> {
  const url = `${restUrl(table)}${params ? `?${params}` : ''}`;
  const res = await fetch(url, { headers: headers(), cache: 'no-store' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Supabase GET ${table} failed (${res.status}): ${text}`);
  }
  return res.json();
}

// Generic POST (insert)
export async function restInsert<T>(table: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(restUrl(table), {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Supabase INSERT ${table} failed (${res.status}): ${text}`);
  }
  const rows = await res.json();
  return rows[0];
}

// Generic POST with upsert (ON CONFLICT)
export async function restUpsert<T>(
  table: string,
  body: Record<string, unknown>,
  onConflict: string
): Promise<T> {
  const h = headers();
  h['Prefer'] = 'return=representation,resolution=merge-duplicates';
  const res = await fetch(`${restUrl(table)}?on_conflict=${onConflict}`, {
    method: 'POST',
    headers: h,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Supabase UPSERT ${table} failed (${res.status}): ${text}`);
  }
  const rows = await res.json();
  return rows[0];
}

// Generic PATCH (update)
export async function restUpdate<T>(table: string, filter: string, body: Record<string, unknown>): Promise<T | null> {
  const res = await fetch(`${restUrl(table)}?${filter}`, {
    method: 'PATCH',
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Supabase PATCH ${table} failed (${res.status}): ${text}`);
  }
  const rows = await res.json();
  return rows[0] || null;
}

// Health check via a simple query
export async function healthCheck(): Promise<boolean> {
  try {
    const rows = await restGet('deepstack_bot_config', 'select=id&limit=1');
    return rows.length > 0;
  } catch {
    return false;
  }
}
