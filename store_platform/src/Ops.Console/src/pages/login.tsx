/**
 * The door.
 *
 * One password, checked on the server, held in an HttpOnly cookie. This console runs on the
 * founder's laptop and is reached over the tailnet, so the threat it defends against is not a
 * stranger on the internet — it is a device on the tailnet, or a phone left unlocked, reaching a
 * page that can pause the engine and rewrite config.yaml.
 */
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';

import { Button, Note, Problem } from '@/components/ui';

export default function Login() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    fetch('/api/ops/session', { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((j: { configured?: boolean; signed_in?: boolean }) => {
        setConfigured(Boolean(j.configured));
        if (j.signed_in) void router.replace('/');
      })
      .catch(() => setConfigured(null));
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch('/api/ops/session', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      const body = (await res.json()) as { ok?: boolean; error?: string };
      if (res.ok && body.ok) {
        window.location.href = '/';
        return;
      }
      setError(body.error || 'That did not work.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center gap-4 px-4 py-10">
      <div>
        <h1 className="font-mono text-[15px] font-[520]">prospector ops</h1>
        <p className="mt-1 text-[13px] text-muted">
          Engine and shelf admin. Signed-in sessions last 12 hours.
        </p>
      </div>

      {configured === false ? (
        <Problem>
          CONTROL_CENTER_PASSWORD is not set, so there is nothing to sign in against. Set it in
          <span className="font-mono"> .env</span> and restart the console. An unconfigured portal
          stays closed.
        </Problem>
      ) : null}

      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="text-[13px] text-muted" htmlFor="pw">
          Password
        </label>
        <input
          id="pw"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="tap rounded-sm border border-border-control bg-surface px-3 font-mono text-[16px]"
          // 16px, not smaller. iOS Safari zooms the whole page on focus of any input below 16px,
          // and the zoom does not come back — the founder then meets a horizontally scrolled page.
        />
        {error ? <Problem>{error}</Problem> : null}
        <Button type="submit" kind="primary" disabled={busy || configured === false}>
          {busy ? 'checking…' : 'Sign in'}
        </Button>
      </form>

      <Note>
        This console reads and writes the engine on this machine. It is not on the public internet
        and must never be exposed there.
      </Note>
    </main>
  );
}
