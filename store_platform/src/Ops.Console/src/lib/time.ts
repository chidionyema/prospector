/**
 * Time rendering.
 *
 * Founder requirement, verbatim: "a run row with no time on it is not acceptable." Every run
 * shows four facts — when it started, when it ended, how long it took, how long ago that was —
 * and every panel says when its data was read.
 *
 * The rule these functions encode: an ABSENT time renders as a named absence, never as `0`,
 * `—`, or a blank. A null that looks like a number is how a dashboard reports an outage as a
 * measurement.
 */

export const ABSENT = 'not recorded';

/** Seconds since `iso`, or null when there is no usable timestamp. */
export function ageSeconds(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  return Math.max(0, (now - t) / 1000);
}

/** `18 min ago`, `2 days ago`, `just now`. Never a bare number. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  const s = ageSeconds(iso, now);
  if (s === null) return ABSENT;
  return `${duration(s)} ago`;
}

/** `2m 41s`, `1h 04m`, `3 days`. Reads at a glance; no decimals above a minute. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return ABSENT;
  const s = Math.max(0, seconds);
  if (s < 1) return 'under a second';
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) {
    const m = Math.floor(s / 60);
    const rem = Math.round(s % 60);
    return rem ? `${m}m ${String(rem).padStart(2, '0')}s` : `${m}m`;
  }
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    return m ? `${h}h ${String(m).padStart(2, '0')}m` : `${h}h`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.round((s % 86400) / 3600);
  return h ? `${d}d ${h}h` : `${d}d`;
}

/**
 * `04:12` for today, `16 Aug 04:12` otherwise, in the viewer's own timezone.
 *
 * Local, not UTC, because the operator is deciding "did that run before or after I changed the
 * config" and does the arithmetic in the timezone they are standing in.
 */
export function clock(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return ABSENT;
  const t = new Date(iso);
  if (!Number.isFinite(t.getTime())) return ABSENT;
  const today = new Date(now);
  const sameDay =
    t.getFullYear() === today.getFullYear() &&
    t.getMonth() === today.getMonth() &&
    t.getDate() === today.getDate();
  const hh = String(t.getHours()).padStart(2, '0');
  const mm = String(t.getMinutes()).padStart(2, '0');
  if (sameDay) return `${hh}:${mm}`;
  const day = t.getDate();
  const month = t.toLocaleString(undefined, { month: 'short' });
  return `${day} ${month} ${hh}:${mm}`;
}

/** The four time facts every run row must carry. */
export type RunTimes = {
  started: string;
  ended: string;
  took: string;
  ago: string;
  running: boolean;
};

export function runTimes(
  firstTs: string | null | undefined,
  lastTs: string | null | undefined,
  now = Date.now(),
): RunTimes {
  const start = firstTs ? Date.parse(firstTs) : NaN;
  const end = lastTs ? Date.parse(lastTs) : NaN;
  // A run whose last event is recent and whose log has not closed is treated as still running.
  // 15 minutes is well above the observed gap between events inside one vet and well below the
  // 3-hour tick deadline, so it cannot label a finished run as live for long.
  const running = Number.isFinite(end) && now - end < 15 * 60 * 1000;
  return {
    started: clock(firstTs, now),
    ended: running ? 'still running' : clock(lastTs, now),
    took:
      Number.isFinite(start) && Number.isFinite(end)
        ? duration((end - start) / 1000)
        : ABSENT,
    ago: ago(lastTs, now),
    running,
  };
}

/** How stale a panel's own reading is. Amber past a minute — see `AsOf`. */
export function freshness(asOfUnix: number | null | undefined, now = Date.now()): {
  label: string;
  stale: boolean;
} {
  if (!asOfUnix) return { label: ABSENT, stale: true };
  const s = Math.max(0, now / 1000 - asOfUnix);
  return { label: `read ${duration(s)} ago`, stale: s > 60 };
}
