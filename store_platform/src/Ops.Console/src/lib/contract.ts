/**
 * The shape the engine gateway speaks, and the client-side calls that fetch it.
 *
 * Kept apart from `lib/ops.ts` on purpose: that module spawns a Python process and can only ever
 * run on the server. Importing a type from it into a page would drag `node:child_process` into
 * the browser bundle. This file has no imports at all.
 */

export type Envelope<T = unknown> = {
  ok: boolean;
  contract: number;
  view?: string;
  action?: string;
  /** Unix seconds. When the engine READ the data — not when the browser rendered it. */
  as_of: number;
  as_of_iso: string;
  took_ms: number;
  data: T | null;
  error: string | null;
  error_kind: string | null;
};

export type Loadable<T> =
  | { state: 'loading'; envelope: null; error: null }
  | { state: 'ready'; envelope: Envelope<T>; error: null }
  | { state: 'failed'; envelope: null; error: string };

/** GET a read view. Throws only on a transport failure; an engine error comes back in the envelope. */
export async function readView<T = unknown>(
  view: string,
  args: Record<string, string | number | undefined> = {},
): Promise<Envelope<T>> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(args)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  }
  const url = `/api/ops/read/${encodeURIComponent(view)}${qs.toString() ? `?${qs}` : ''}`;
  const res = await fetch(url, { credentials: 'same-origin' });
  const body = (await res.json()) as Envelope<T>;
  if (res.status === 401) {
    // The session expired while the page was open. Send them back to the door rather than
    // rendering an empty dashboard, which reads as "the engine is dead".
    if (typeof window !== 'undefined') window.location.href = '/login';
  }
  return body;
}

export type ActResult<T = Record<string, unknown>> = {
  status: number;
  envelope: Envelope<T>;
};

/**
 * Step one of a write: ask what would change. Never writes.
 */
export async function previewAction<T = Record<string, unknown>>(
  action: string,
  payload: Record<string, unknown>,
): Promise<ActResult<T>> {
  return post(action, { payload, preview: true });
}

/**
 * Step two: write, quoting the token the preview returned.
 *
 * There is no single-step form of this function, and that is the point. The token is verified in
 * Python, so even a caller that skipped the preview lands on the same refusal.
 */
export async function applyAction<T = Record<string, unknown>>(
  action: string,
  payload: Record<string, unknown>,
  confirm: string,
): Promise<ActResult<T>> {
  return post(action, { payload, confirm });
}

async function post<T>(action: string, body: unknown): Promise<ActResult<T>> {
  const res = await fetch(`/api/ops/act/${encodeURIComponent(action)}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const envelope = (await res.json()) as Envelope<T>;
  return { status: res.status, envelope };
}

/**
 * The confirmation token a preview handed back.
 *
 * The gateway calls the field `confirm` (`console_api.py:1425`) and puts it inside `data`, next
 * to the preview it belongs to. Reading it through one function means a page cannot invent a
 * second spelling and silently always fail the fence.
 */
export function confirmTokenOf(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null;
  const t = (data as Record<string, unknown>).confirm;
  return typeof t === 'string' && t ? t : null;
}
