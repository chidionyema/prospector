/**
 * The Node end of the central log ingest. `docs/LOGGING_AND_RETENTION.md` Part 4.
 *
 * The engine daemons ship through `prospector/log_shipper.py` and `Store.Api` ships through
 * `Store.Api/Infrastructure/CentralLog/`. The two Next apps, the storefront and the ops
 * console, shipped nothing, so the two surfaces a person actually looks at were the two the
 * central log could not answer for. This is their producer.
 *
 * ── THIS FILE EXISTS TWICE, BYTE FOR BYTE ────────────────────────────────────────────────────
 * `Store.Web/src/lib/centralLog.ts` and `Ops.Console/src/lib/centralLog.ts` are separate Next
 * builds with separate `package.json` files and no workspace between them, so neither can import
 * the other's `src/`. Copying it is the smallest change that works; the risk copying carries is
 * that a redaction fix lands in one app and not the other. That risk is closed by a test in EACH
 * app's suite (`centralLogDoesNotDrift.test.ts`), each reading both copies off disk. It is in
 * both suites rather than in the Python suite on purpose: CI decides its lanes from the changed
 * paths (`.github/workflows/ci.yml`, the `wb` and `cn` filters), so a pull request touching only
 * the console runs only the console's tests. A single drift test in any one lane would be skipped
 * by exactly the change it exists to catch.
 *
 * ── IT NEVER THROWS AND IT NEVER BLOCKS ──────────────────────────────────────────────────────
 * Every entry point swallows. A logger that can turn a handled 401 into an unhandled 500 is
 * worse than no logger, and the callers here are already on a failure path.
 *
 * ── IT DROPS, IT DOES NOT RETRY ──────────────────────────────────────────────────────────────
 * A failed POST discards the batch and counts it. Retrying would grow a queue during exactly the
 * outage that caused the failure, which is the backpressure `prospector/log_ingest.py` refuses at
 * the other end for the same reason. Losing a log line is a cost; stalling the storefront to keep
 * one is an outage.
 *
 * ── SERVER ONLY ──────────────────────────────────────────────────────────────────────────────
 * The ingest key would be readable by anyone who opened devtools if this ran in a browser, and
 * the ingest is private-network only, so a browser could not reach it anyway. `configured()`
 * returns false when `window` exists, and the browser reaches the ingest through a server route
 * (`Store.Web/src/pages/api/client-log.ts`) which is where the key stays.
 */

/** The engine's ingest over Fly's private network. Same default as `log_shipper.py:35`. */
const DEFAULT_URL = 'http://prospector-engine.internal:8613/internal/logs';

/** Lines held before the oldest is dropped. A bound, not a target: see the drop rule above. */
const CAPACITY = 1000;

/** Lines per POST. `log_ingest.py` caps a batch at 1000 lines and 1MB. */
const BATCH = 200;

/** How long a full buffer waits before it is sent. */
const INTERVAL_MS = 2000;

/** A POST that has not answered by here is treated as failed. */
const TIMEOUT_MS = 3000;

/** `msg` is clipped, never dropped. A stack is evidence; a 200KB stack is a log hose. */
const MAX_MSG = 2000;
const MAX_CTX_VALUE = 512;

/**
 * `svc` becomes part of a FILENAME at the other end. `log_ingest.py` anchors the same pattern as
 * its security gate: it is what stops `svc: "../../../etc/cron.d/x"`, and rejects the batch if
 * it fails. Checking it here too means a bad service name is a build-time constant somebody can
 * see, not a batch that silently 400s in production.
 */
const SVC_RE = /^[a-z][a-z0-9-]{0,31}$/;

/** `evt` is a machine name: lowercase, dot-separated, never interpolated with a value. */
const EVT_RE = /[^a-z0-9._-]+/g;

/**
 * Field NAMES that must never travel, matched on the name and not the value. Kept character for
 * character in step with `prospector/log_shipper.py:52`: a value scan cannot recognise a shape it
 * has not seen before, and a name scan cannot be fooled by a new provider's format.
 */
const SECRET_NAME_RE =
  /key|secret|token|password|passwd|credential|authorization|auth|cookie|session|pem|private/i;

export type Level = 'debug' | 'info' | 'warn' | 'error' | 'crit';

export type LineInput = {
  svc: string;
  evt: string;
  lvl?: Level;
  msg?: string;
  corr?: string | null;
  ctx?: Record<string, unknown>;
};

/** One Part 4.4 line. `host` is absent on purpose: the ingest sets it from the connection. */
export type Line = {
  ts: string;
  svc: string;
  lvl: Level;
  evt: string;
  msg?: string;
  corr?: string;
  ctx?: Record<string, string | number | boolean | null>;
};

export const counters = {
  queued: 0,
  sent: 0,
  dropped_full: 0,
  dropped_malformed: 0,
  dropped_unconfigured: 0,
  failed_posts: 0,
};

export function ingestUrl(): string {
  return (process.env.PROSPECTOR_LOG_INGEST_URL || DEFAULT_URL).trim();
}

export function ingestKey(): string {
  return (process.env.STORE_INTERNAL_API_KEY || '').trim();
}

/**
 * Whether a line can go anywhere. False in a browser, and false with no key, in which case every
 * caller here still writes its own stderr line, the behaviour that existed before this file.
 */
export function configured(): boolean {
  if (typeof window !== 'undefined') return false;
  return ingestKey() !== '' && ingestUrl() !== '';
}

function eventName(raw: string): string {
  const cleaned = raw.trim().toLowerCase().replace(EVT_RE, '.').replace(/^\.+|\.+$/g, '');
  return (cleaned || 'log.unnamed').slice(0, 128);
}

/** Flat by construction, so no nested shape can surprise a reader or blow the line cap. */
function safe(value: unknown): string | number | boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (typeof value === 'string') return value.slice(0, MAX_CTX_VALUE);
  try {
    return JSON.stringify(value).slice(0, MAX_CTX_VALUE);
  } catch {
    return String(value).slice(0, MAX_CTX_VALUE);
  }
}

export function toLine(input: LineInput): Line {
  const line: Line = {
    // `toISOString()` is already the ingest's shape: UTC, exactly three fractional digits, `Z`.
    ts: new Date().toISOString(),
    svc: input.svc,
    lvl: input.lvl || 'info',
    evt: eventName(input.evt),
  };
  if (input.msg) line.msg = String(input.msg).slice(0, MAX_MSG);
  if (input.corr) line.corr = String(input.corr).slice(0, 128);
  const ctx: Record<string, string | number | boolean | null> = {};
  for (const [name, value] of Object.entries(input.ctx || {})) {
    if (value === undefined) continue;
    ctx[name] = SECRET_NAME_RE.test(name) ? '[redacted]' : safe(value);
  }
  if (Object.keys(ctx).length > 0) line.ctx = ctx;
  return line;
}

let queue: Line[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let sending = false;

/**
 * Queue one line. Returns whether it was queued, for tests and for a caller that wants to know
 * it is logging into a void; no caller is expected to act on it.
 */
export function ship(input: LineInput): boolean {
  try {
    if (!configured()) {
      counters.dropped_unconfigured += 1;
      return false;
    }
    if (!SVC_RE.test(input.svc)) {
      counters.dropped_malformed += 1;
      return false;
    }
    const line = toLine(input);
    if (queue.length >= CAPACITY) {
      queue.shift();
      counters.dropped_full += 1;
    }
    queue.push(line);
    counters.queued += 1;
    schedule();
    return true;
  } catch {
    counters.dropped_malformed += 1;
    return false;
  }
}

function schedule(): void {
  if (timer !== null) return;
  timer = setTimeout(() => {
    timer = null;
    void flush();
  }, INTERVAL_MS);
  // Do not hold a process open for a log line. `next build` runs pages in a short-lived
  // process; an active timer there would keep it alive past its work.
  if (typeof timer === 'object' && timer !== null && 'unref' in timer) {
    (timer as { unref: () => void }).unref();
  }
}

/** Send everything queued. Awaited by tests and by a route that wants its line gone before it
 *  answers; the timer path never awaits it. */
export async function flush(): Promise<void> {
  if (sending) return;
  sending = true;
  try {
    while (queue.length > 0) {
      const batch = queue.slice(0, BATCH);
      queue = queue.slice(batch.length);
      await post(batch);
    }
  } catch {
    /* a failure here is already counted in post(); nothing above can act on it */
  } finally {
    sending = false;
  }
}

async function post(lines: Line[]): Promise<boolean> {
  if (lines.length === 0) return true;
  let body = '';
  try {
    body = lines.map((line) => JSON.stringify(line)).join('\n') + '\n';
  } catch {
    counters.dropped_malformed += lines.length;
    return false;
  }
  try {
    const response = await fetch(ingestUrl(), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${ingestKey()}`,
        'Content-Type': 'application/x-ndjson',
      },
      body,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (response.ok) {
      counters.sent += lines.length;
      return true;
    }
  } catch {
    // Every failure is the same failure: the line does not arrive. DNS, refused, 500, timeout,
    // a proxy. None of them may reach the caller and none is worth its own branch.
  }
  counters.failed_posts += 1;
  return false;
}

/** For tests. Empties the buffer and the counters without sending anything. */
export function reset(): void {
  queue = [];
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
  sending = false;
  for (const name of Object.keys(counters) as (keyof typeof counters)[]) counters[name] = 0;
}
