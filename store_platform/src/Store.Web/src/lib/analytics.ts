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
  | 'checkout_completed'
  | 'pack_shared'
  | 'basket_removed'
  | 'matchmaker_answered'
  | 'palette_search'
  | 'copy_variant'
  | 'price_viewed'
  | 'checkout_started';

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

/**
 * The pricing instrument (build plan D2). `price_viewed` is the denominator and
 * `checkout_started` the numerator of the only conversion rate that moves fast enough to
 * evaluate a ladder change -- purchases are far too rare an event to learn from, which is the
 * whole argument for these two existing.
 *
 * `pack_id` and `price_pence` are the required fields, and `price_pence` is ALSO the rung: the
 * ladder is a fixed set of seven values (`config.yaml listing.pricing.rungs`), so pence maps to
 * a rung one-to-one and a separate rung field would be a second source of truth for one fact --
 * free to disagree with the price it claims to label. Which ladder was in force is recovered by
 * joining on the event's server-side `CreatedAt`, not by trusting a label the browser wrote.
 *
 * Emits NOTHING when `pricePence` is absent, which is what an older API serves. A beacon
 * carrying `null` would be counted as a view at an unknown price, and a denominator inflated by
 * unknowns is worse than a smaller honest one.
 *
 * Not deduplicated: the unique index is filtered to `Name = 'checkout_completed'`
 * (`20260731124037_DropAnalyticsSessionId.cs:45-50`), so repeat views at the same price are
 * counted repeatedly -- which is exactly what a denominator has to do.
 */
export function trackPriceEvent(
  name: 'price_viewed' | 'checkout_started',
  pack: { id: string; pricePence?: number },
): void {
  if (typeof pack.pricePence !== 'number' || !Number.isFinite(pack.pricePence)) return;
  track(name, JSON.stringify({ pack_id: pack.id, price_pence: pack.pricePence }));
}
