/**
 * One hook for every read panel.
 *
 * Reads happen in the BROWSER, not in `getServerSideProps`. Two reasons, both measured rather
 * than assumed: a server-rendered page bakes its `as_of` into the HTML, so a page left open in a
 * backgrounded Telegram webview shows an hour-old number with no way to tell — the exact
 * prose-drift failure the "state is a probe" rule exists to stop. And the gateway call costs
 * ~0.3–1.1s, which as a server render is 1.1s of blank screen.
 *
 * EVERY PANEL POLLS, and that is the change of 2026-08-18. Founder: "portal needs to be more
 * intelligent and real time". Polling used to be opt-in and off by default, because a console
 * that polls everything spawns a Python process forever. Two things make the default safe now:
 * only the MOUNTED page reads, and a hidden tab reads nothing at all (`document.hidden`), so a
 * console left open in a background tab costs nothing until it is looked at. On becoming visible
 * it re-reads at once, so the first thing an operator sees is current rather than an hour old.
 *
 * `pollMs: 0` still turns it off, and one panel uses that: the config editor, where a re-read
 * underneath a half-typed form would throw the operator's edit away.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import type { Envelope } from '@/lib/contract';
import { readView } from '@/lib/contract';

/**
 * How often a panel re-reads when the caller says nothing. 30s is one gateway spawn per 30s
 * against views that measured 0.6-2.3s in the container on 2026-08-18, and it is fast enough
 * that a brain going down, a queue draining or a payment landing shows up while the operator
 * is still looking at the page.
 */
export const DEFAULT_POLL_MS = 30_000;

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

  // Polling, and the visibility gate that pays for it. A hidden tab does not read: the timer
  // still fires, but it skips, so a console left open overnight spawns nothing. Coming back to
  // the tab reads immediately rather than waiting out the interval.
  const ms = opts.pollMs === undefined ? DEFAULT_POLL_MS : opts.pollMs;
  useEffect(() => {
    if (!ms || !view || stop) return;
    const hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';
    const id = setInterval(() => {
      if (hidden()) return;
      setTick((n) => n + 1);
    }, ms);
    const onVisible = () => {
      if (!hidden()) setTick((n) => n + 1);
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisible);
    }
    return () => {
      clearInterval(id);
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisible);
      }
    };
  }, [ms, view, stop]);

  return {
    data,
    envelope,
    error: result?.error ?? null,
    loading: view !== null && result?.key !== key,
    refresh,
  };
}
