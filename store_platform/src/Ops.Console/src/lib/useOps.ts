/**
 * One hook for every read panel.
 *
 * Reads happen in the BROWSER, not in `getServerSideProps`. Two reasons, both measured rather
 * than assumed: a server-rendered page bakes its `as_of` into the HTML, so a page left open in a
 * backgrounded Telegram webview shows an hour-old number with no way to tell — the exact
 * prose-drift failure the "state is a probe" rule exists to stop. And the gateway call costs
 * ~0.3–1.1s, which as a server render is 1.1s of blank screen.
 *
 * Polling is OPT-IN per panel and defaults to off. A console that polls everything every five
 * seconds spawns a Python process every five seconds, forever, on the founder's laptop.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import type { Envelope } from '@/lib/contract';
import { readView } from '@/lib/contract';

export type OpsState<T> = {
  data: T | null;
  envelope: Envelope<T> | null;
  error: string | null;
  loading: boolean;
  /** Re-read now. Every panel gets a manual refresh; nothing here is a guess about staleness. */
  refresh: () => void;
};

export function useOps<T = unknown>(
  view: string | null,
  args: Record<string, string | number | undefined> = {},
  opts: { pollMs?: number } = {},
): OpsState<T> {
  const [envelope, setEnvelope] = useState<Envelope<T> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(view !== null);
  const [tick, setTick] = useState(0);

  // The args object is a fresh literal on every render, so it cannot be a dependency directly —
  // that is an infinite fetch loop. Serialise it and depend on the string.
  const argKey = JSON.stringify(args);
  const alive = useRef(true);

  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (!view) return;
    let cancelled = false;
    setLoading(true);
    readView<T>(view, JSON.parse(argKey) as Record<string, string>)
      .then((env) => {
        if (cancelled || !alive.current) return;
        setEnvelope(env);
        // The engine's own failure keeps its reason. It is NOT rendered as empty data.
        setError(env.ok ? null : (env.error ?? 'the engine returned no reason'));
      })
      .catch((err: unknown) => {
        if (cancelled || !alive.current) return;
        setEnvelope(null);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled && alive.current) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, argKey, tick]);

  useEffect(() => {
    const ms = opts.pollMs;
    if (!ms || !view) return;
    const id = setInterval(() => setTick((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [opts.pollMs, view]);

  return {
    data: envelope?.ok ? ((envelope.data ?? null) as T | null) : null,
    envelope,
    error,
    loading,
    refresh,
  };
}
