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
  opts: { pollMs?: number; stopWhen?: (data: T | null) => boolean } = {},
): OpsState<T> {
  // ONE piece of state for the result, stamped with the request it answers. `loading` used to be
  // its own `useState` set at the top of the fetch effect, which is an extra render on every read
  // and the thing `react-hooks/set-state-in-effect` flags. Derived from the stamp it costs nothing
  // and cannot disagree with the data beside it.
  const [result, setResult] = useState<{
    key: string;
    envelope: Envelope<T> | null;
    error: string | null;
  } | null>(null);
  const [tick, setTick] = useState(0);

  // The args object is a fresh literal on every render, so it cannot be a dependency directly —
  // that is an infinite fetch loop. Serialise it and depend on the string.
  const argKey = JSON.stringify(args);
  const key = `${view ?? ''}|${argKey}|${tick}`;
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
    readView<T>(view, JSON.parse(argKey) as Record<string, string>)
      .then((env) => {
        if (cancelled || !alive.current) return;
        // The engine's own failure keeps its reason. It is NOT rendered as empty data.
        setResult({
          key,
          envelope: env,
          error: env.ok ? null : (env.error ?? 'the engine returned no reason'),
        });
      })
      .catch((err: unknown) => {
        if (cancelled || !alive.current) return;
        setResult({
          key,
          envelope: null,
          error: err instanceof Error ? err.message : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [view, argKey, tick, key]);

  // The previous answer stays on screen while the next one is in flight. A panel that blanks on
  // every poll is a panel nobody can read.
  const envelope = result?.envelope ?? null;
  const data = envelope?.ok ? ((envelope.data ?? null) as T | null) : null;

  // Polling stops when the caller says the thing being watched has finished. Computed here during
  // render, from data this hook already holds, so no effect has to write state to stop a timer.
  const stop = opts.stopWhen ? opts.stopWhen(data) : false;

  useEffect(() => {
    const ms = opts.pollMs;
    if (!ms || !view || stop) return;
    const id = setInterval(() => setTick((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [opts.pollMs, view, stop]);

  return {
    data,
    envelope,
    error: result?.error ?? null,
    loading: view !== null && result?.key !== key,
    refresh,
  };
}
