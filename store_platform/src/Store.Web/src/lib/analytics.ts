import { recordAnalyticsEvent } from '@/lib/api/client';

/**
 * First-party analytics beacon. Four counters, one endpoint, no third-party script — the
 * point is baseline traffic and conversion numbers, not user profiling. The event names are
 * an allowlist enforced server-side (AnalyticsEndpoints.cs); adding one here without adding
 * it there means it silently 400s, so the type below is the client half of that contract.
 *
 * Privacy posture: no cookie is set. The session id lives in sessionStorage, so it dies with
 * the tab session and links nothing across visits. Only the pathname is sent — never query
 * strings, which can carry order tokens.
 */
export type AnalyticsEventName =
  | 'page_view'
  | 'sample_cta_clicked'
  | 'catalog_cta_clicked'
  | 'checkout_completed';

const SESSION_KEY = 'mc_sid';

function sessionId(): string | null {
  try {
    let sid = window.sessionStorage.getItem(SESSION_KEY);
    if (!sid) {
      sid = crypto.randomUUID();
      window.sessionStorage.setItem(SESSION_KEY, sid);
    }
    return sid;
  } catch {
    // Storage blocked (private mode, hardened browsers): count the event anonymously.
    return null;
  }
}

/** Fire-and-forget. Analytics must never break the page or delay navigation. */
export function track(name: AnalyticsEventName, meta?: string): void {
  if (typeof window === 'undefined') return;
  recordAnalyticsEvent({
    name,
    path: window.location.pathname,
    sessionId: sessionId(),
    meta: meta ?? null,
  });
}

/**
 * Track at most once per browser, keyed by dedupKey — for events a page refresh would
 * otherwise re-fire (the order success page re-mounts on every reload).
 */
export function trackOnce(dedupKey: string, name: AnalyticsEventName, meta?: string): void {
  if (typeof window === 'undefined') return;
  try {
    const storageKey = `mc_evt_${dedupKey}`;
    if (window.localStorage.getItem(storageKey)) return;
    window.localStorage.setItem(storageKey, '1');
  } catch {
    // Storage blocked: a possible double count beats a missing one.
  }
  track(name, meta);
}
