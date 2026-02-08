import crypto from 'node:crypto';

export type CommandEnvelope = {
  schema_version: number;
  command_id: string;
  command: string;
  params: Record<string, unknown>;
  created_at: string;
  expires_at: string;
  nonce: string;
};

function stableStringify(value: unknown): string {
  if (value === null) return 'null';
  const t = typeof value;
  if (t === 'number' || t === 'boolean') return String(value);
  if (t === 'string') return JSON.stringify(value);
  if (t !== 'object') return JSON.stringify(value);

  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(',')}]`;
  }

  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  return `{${keys
    .map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`)
    .join(',')}}`;
}

export function signCommandEnvelope(
  envelope: CommandEnvelope,
  secret: string
): string {
  const canonical = stableStringify(envelope);
  return crypto.createHmac('sha256', secret).update(canonical).digest('hex');
}

export function buildSignedCommandParams(input: {
  commandId: string;
  command: string;
  params: Record<string, unknown>;
  secret: string;
  expiresInSeconds?: number;
}): { params: Record<string, unknown>; envelope: CommandEnvelope; signature: string } {
  const now = new Date();
  const expiresInSeconds = input.expiresInSeconds ?? 60;
  const expires = new Date(now.getTime() + expiresInSeconds * 1000);

  const envelope: CommandEnvelope = {
    schema_version: 1,
    command_id: input.commandId,
    command: input.command,
    params: input.params ?? {},
    created_at: now.toISOString(),
    expires_at: expires.toISOString(),
    nonce: crypto.randomBytes(16).toString('hex'),
  };

  const signature = signCommandEnvelope(envelope, input.secret);

  const signedParams: Record<string, unknown> = {
    ...input.params,
    command_id: envelope.command_id,
    schema_version: envelope.schema_version,
    created_at: envelope.created_at,
    expires_at: envelope.expires_at,
    nonce: envelope.nonce,
    signature,
  };

  return { params: signedParams, envelope, signature };
}

export function getCommandHmacSecret(): string {
  const secret = process.env.BOT_COMMAND_HMAC_SECRET || '';
  if (!secret) {
    throw new Error('BOT_COMMAND_HMAC_SECRET is required to sign bot commands');
  }
  return secret;
}

