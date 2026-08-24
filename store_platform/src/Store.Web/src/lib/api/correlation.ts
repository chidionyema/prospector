/**
 * The buyer's end of the correlation id.
 *
 * The chain the logging design asks for starts in the browser: one id on the request, stamped
 * onto the Stripe Checkout Session by the API, read back by the webhook minutes later, and
 * written onto every fulfilment line. Without this file the chain starts at the API, so a
 * question that begins "this buyer says the download never arrived" has no way to reach the
 * click that started it.
 *
 * ── One id per tab, not per request ───────────────────────────────────────────────────────────
 * A buyer's visit is one story: browse, price, checkout, return from Stripe. Sharing the id
 * across those calls is what makes the story greppable as a unit. Per-request ids would still
 * join a single checkout to its own webhook, and nothing else. The API gives every request its
 * own trace id regardless, so nothing is lost by the coarser grain here.
 *
 * ── It must survive the API's sanitiser ───────────────────────────────────────────────────────
 * Store.Api keeps only `[A-Za-z0-9._-]` and truncates at 64 characters
 * (Store.Api/Common/HttpContextExtensions.cs). A uuid is 36 characters of hex and dashes, so it
 * passes through unchanged. Anything invented here that did not would be silently rewritten, and
 * the two ends would name the same visit differently.
 */

export const CORRELATION_HEADER = 'X-Correlation-Id';

/** sessionStorage, not localStorage: the id belongs to this tab's visit, not to the device. */
const STORAGE_KEY = 'mc.correlationId';

/** Survives a sessionStorage that throws, which is Safari's private mode. */
let inMemory: string | null = null;

function mint(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  if (c && typeof c.getRandomValues === 'function') {
    const bytes = c.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  }
  // No crypto at all. The id is a log join key, never a secret or a token, so a weak random
  // value is a worse join key and nothing more. Returning null instead would lose the chain.
  return `f${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
}

/**
 * This tab's correlation id, or null on the server.
 *
 * Null rather than a fresh id server-side: a server render is not a buyer action, and minting one
 * per render would put thousands of ids into the logs that no browser ever sends again.
 */
export function correlationId(): string | null {
  if (typeof window === 'undefined') return null;
  if (inMemory) return inMemory;
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    if (stored) {
      inMemory = stored;
      return stored;
    }
  } catch {
    /* storage disabled; fall through to a per-tab in-memory id */
  }
  inMemory = mint();
  try {
    window.sessionStorage.setItem(STORAGE_KEY, inMemory);
  } catch {
    /* nothing to do: the in-memory copy still holds for this tab */
  }
  return inMemory;
}

/**
 * Add the correlation header to a fetch's headers.
 *
 * Every call to our own API goes through this. `correlationHeaders.test.ts` scans the api lib and
 * fails when a fetch to the store API does not, because the failure mode of forgetting one is
 * invisible: the request succeeds, and only the trail is missing.
 */
export function correlated(headers?: Record<string, string>): Record<string, string> {
  const id = correlationId();
  return id ? { ...headers, [CORRELATION_HEADER]: id } : { ...headers };
}
