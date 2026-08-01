import { recordAnalyticsEvent } from '@/lib/api/client';

/**
 * First-party analytics beacon. Four counters, one endpoint, no third-party script, the
 * point is baseline traffic and conversion numbers, not user profiling. The event names are
 * an allowlist enforced server-side (AnalyticsEndpoints.cs); adding one here without adding
 * it there means it silently 400s, so the type below is the client half of that contract.
 *
 * Privacy posture, READ BEFORE ADDING ANYTHING HERE: this module writes NOTHING to the
 * visitor's device. No cookie, no localStorage, no sessionStorage. That is not a stylistic
 * preference, it is what keeps the storefront out of PECR reg 6(1), which bans storing
 * information "in the terminal equipment of a subscriber or user" without consent, note it
 * says *information*, not *cookies*, so web storage counts. The only exemption (reg 6(4)(b))
 * is storage "strictly necessary" for a service the visitor asked for, and measuring our own
 * conversion rate is not something they asked for. The site has no consent UI, so the only
 * compliant analytics is analytics that stores nothing.
 *
 * The first cut of this file minted a per-tab session id into sessionStorage. It was removed
 * because it was both non-compliant and useless: no report ever read it.
 *
 * Only the pathname is sent, never query strings, which can carry order tokens.
 */
export type AnalyticsEventName =
  | 'page_view'
  | 'sample_cta_clicked'
  | 'catalog_cta_clicked'
  | 'checkout_completed';

/**
 * Fire-and-forget. Analytics must never break the page or delay navigation.
 *
 * Safe to call more than once for the same logical event: events a reload would re-fire are
 * deduplicated server-side on (name, meta) rather than by marking the visitor's device.
 */
export function track(name: AnalyticsEventName, meta?: string): void {
  if (typeof window === 'undefined') return;
  recordAnalyticsEvent({
    name,
    path: window.location.pathname,
    meta: meta ?? null,
  });
}
