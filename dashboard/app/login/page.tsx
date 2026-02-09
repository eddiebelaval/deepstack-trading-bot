'use client';

import { Suspense, useState, FormEvent } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

function LoginForm() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });

      if (response.ok) {
        const from = searchParams.get('from') || '/';
        // Prevent open redirect — only allow relative paths on this origin
        const safePath = from.startsWith('/') && !from.startsWith('//') ? from : '/';
        router.push(safePath);
      } else {
        const data = await response.json();
        setError(data.error || 'Authentication failed');
      }
    } catch {
      setError('Connection failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      {/* Terminal header */}
      <div className="border border-terminal-green/30 rounded-t-lg bg-terminal-bg-elevated">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-terminal-green/20">
          <div className="w-2 h-2 rounded-full bg-terminal-red" />
          <div className="w-2 h-2 rounded-full bg-terminal-amber" />
          <div className="w-2 h-2 rounded-full bg-terminal-green" />
          <span className="ml-2 text-[10px] text-terminal-dim tracking-wider">DEEPSTACK AUTH</span>
        </div>

        <div className="p-6 space-y-6">
          {/* ASCII art logo — Claude Code block style */}
          <pre
            className="text-terminal-green text-[10px] leading-tight font-mono text-center select-none"
            style={{ textShadow: '0 0 10px rgba(0, 170, 43, 0.3), 0 0 20px rgba(0, 170, 43, 0.1)' }}
          >
{`██████    ████████  ████████  ████████
██    ██  ██        ██        ██    ██
██    ██  ██████    ██████    ████████
██    ██  ██        ██        ██
██████    ████████  ████████  ██

████████  ████████    ████    ████████  ██    ██
██          ████    ██    ██  ██        ██  ██
████████    ████    ████████  ██        ████
      ██    ████    ██    ██  ██        ██  ██
████████    ████    ██    ██  ████████  ██    ██`}
          </pre>

          <div className="text-center">
            <div className="text-[10px] text-terminal-dim mt-1">Control Plane Authentication</div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-[10px] text-terminal-dim tracking-[0.15em] uppercase mb-2">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                className="w-full px-3 py-2.5 bg-terminal-bg border border-terminal-green/30 rounded text-sm text-terminal-green font-mono
                  focus:outline-none focus:border-terminal-green/60 focus:shadow-[0_0_10px_rgba(0,255,65,0.1)]
                  placeholder:text-terminal-dim/30"
                placeholder="Enter access code..."
              />
            </div>

            {error && (
              <div className="text-xs text-terminal-red border border-terminal-red/30 bg-terminal-red/10 px-3 py-2 rounded">
                ACCESS DENIED: {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !password}
              className={`w-full py-2.5 text-xs font-bold border rounded transition-all duration-200 ${
                loading || !password
                  ? 'border-terminal-dim/20 text-terminal-dim/40 cursor-not-allowed'
                  : 'border-terminal-green text-terminal-green hover:bg-terminal-green/15 hover:shadow-[0_0_15px_rgba(0,255,65,0.2)]'
              }`}
            >
              {loading ? 'AUTHENTICATING...' : 'AUTHENTICATE'}
            </button>
          </form>
        </div>
      </div>

      <div className="text-center mt-4 text-[9px] text-terminal-dim/30">
        DEEPSTACK v2.1.0 | id8Labs
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-screen terminal flex items-center justify-center p-4">
      <Suspense fallback={
        <div className="text-terminal-dim text-sm">Loading...</div>
      }>
        <LoginForm />
      </Suspense>
    </div>
  );
}
