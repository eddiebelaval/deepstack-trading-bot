import { describe, it, expect } from 'vitest';
import crypto from 'node:crypto';

import { signCommandEnvelope, type CommandEnvelope, buildSignedCommandParams } from '@/lib/command-signing';

describe('command signing', () => {
  it('signCommandEnvelope returns stable sha256 hmac hex', () => {
    const envelope: CommandEnvelope = {
      schema_version: 1,
      command_id: '11111111-1111-1111-1111-111111111111',
      command: 'pause',
      params: {},
      created_at: '2026-02-07T00:00:00.000Z',
      expires_at: '2026-02-07T00:01:00.000Z',
      nonce: 'abcdabcdabcdabcdabcdabcdabcdabcd',
    };

    const sig = signCommandEnvelope(envelope, 'test_secret');
    expect(sig).toMatch(/^[a-f0-9]{64}$/);
  });

  it('buildSignedCommandParams attaches required meta fields', () => {
    const inputParams = { strategy: 'momentum', enabled: true };
    const { params } = buildSignedCommandParams({
      commandId: crypto.randomUUID(),
      command: 'toggle_strategy',
      params: inputParams,
      secret: 'test_secret',
      expiresInSeconds: 60,
    });

    expect(params.signature).toBeDefined();
    expect(params.nonce).toBeDefined();
    expect(params.created_at).toBeDefined();
    expect(params.expires_at).toBeDefined();
    expect(params.schema_version).toBe(1);
    expect(params.command_id).toBeDefined();
    expect(params.strategy).toBe('momentum');
  });
});

