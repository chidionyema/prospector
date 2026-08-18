import { recordAnalyticsEvent } from '@/lib/api/client';

/**
 * First-party analytics beacon. Four counters, one endpoint, no third-party script, the
 * point is baseline traffic and conversion numbers, not user profiling. The event names are
 * an allowlist enforced server-side (AnalyticsEndpoints.cs); adding one here without adding
 * it there means it silently 400s, so the type below is the client half of that contract.
 *
 * Privacy posture: this module stores one per-tab id in sessionStorage and nothing else. No
 * cookie, no localStorage, no cross-site identifier, no profile. An earlier version of this
 * docblock claimed a blanket PECR reg 6(1) prohibition on any web storage and used that to
 * ban a session id outright. That reading was wrong and the founder corrected it on
 * 2026-08-16; the ban is removed rather than worked around, so the next reader does not
 * re-derive it. The id is per-tab, random, and dies with the tab.
 *
 * The id earns its place: without it, an impression count and a click count are two separate
 * totals that cannot be divided. Click-through rate is a ratio over the SAME visitor's
 * cards, so joining the two requires a key, and a per-tab random string is the smallest key
 * that does the job.
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
  | 'checkout_started'
  // The title instrument. `card_impression` is the denominator and `card_click` the
  // numerator of catalogue click-through, which is the only signal fast enough to choose
  // between title forms: every catalogue view is 60-odd trials, where a purchase is one
  // rare trial. Adding these two here without adding them to AnalyticsEndpoints.cs would
  // make them 400 silently, and a dropped beacon looks exactly like a card nobody clicked.
  | 'card_impression'
  | 'card_click'
  // The FAQ helpfulness control. Meta is `<question-slug>:up|down`, so a reorder of the list
  // cannot re-point historic votes at a different question. Adding this here without adding it
  // to AnalyticsEndpoints.cs would 400 silently, which reads as "nobody voted".
  | 'faq_helpful';

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

/**
 * The server truncates Meta at 512 characters rather than rejecting the beacon
 * (`AnalyticsEndpoints.cs` RecordAsync, `Truncate(request.Meta, 512)`). Truncation is the
 * right call for a free-text note and the wrong one for a list: a batch of card ids that
 * runs past the limit is not shortened, it is corrupted into invalid JSON, and every id
 * after the cut is counted nowhere. The catalogue renders 60-plus cards, so one beacon
 * carrying all of them would overrun this every single time. Hence chunking.
 */
export const CARD_META_LIMIT = 512;

const SESSION_KEY = 'mc_sid';

/**
 * A random per-tab id, minted on first use. Returns '' when storage is unavailable
 * (Safari private mode throws on setItem). The beacons still fire, they just cannot be
 * joined into a ratio. A raw count with no session id is still a count; dropping the beacon
 * would lose it altogether.
 */
export function sessionId(): string {
  if (typeof window === 'undefined') return '';
  try {
    const existing = window.sessionStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    const minted = (
      window.crypto?.randomUUID?.() ?? `${Math.random()}${Math.random()}`
    ).replace(/[^a-z0-9]/gi, '').slice(0, 16);
    window.sessionStorage.setItem(SESSION_KEY, minted);
    return minted;
  } catch {
    return '';
  }
}

/**
 * Split pack ids into meta payloads that each fit under `limit`.
 *
 * Pure and exported so the limit is proven by a test rather than by arithmetic in a
 * comment. Keys are single letters (`s` session, `p` packs) because every wasted character
 * is one fewer id per beacon.
 *
 * An id whose payload exceeds the limit on its own is still emitted: one truncated beacon
 * is a better failure than a silently dropped card.
 */
export function chunkCardIds(sid: string, ids: string[], limit = CARD_META_LIMIT): string[] {
  const encode = (batch: string[]) => JSON.stringify({ s: sid, p: batch });
  const out: string[] = [];
  let batch: string[] = [];
  for (const id of ids) {
    const next = [...batch, id];
    if (batch.length > 0 && encode(next).length > limit) {
      out.push(encode(batch));
      batch = [id];
    } else {
      batch = next;
    }
  }
  if (batch.length > 0) out.push(encode(batch));
  return out;
}

/** The CTR denominator: cards that actually entered the viewport. */
export function trackCardImpressions(packIds: string[]): void {
  if (typeof window === 'undefined' || packIds.length === 0) return;
  for (const meta of chunkCardIds(sessionId(), packIds)) {
    track('card_impression', meta);
  }
}

/** The CTR numerator. `i` is the card's position in the list, so rank can be controlled for. */
export function trackCardClick(packId: string, position?: number): void {
  track(
    'card_click',
    JSON.stringify({ s: sessionId(), p: packId, i: typeof position === 'number' ? position : null }),
  );
}
