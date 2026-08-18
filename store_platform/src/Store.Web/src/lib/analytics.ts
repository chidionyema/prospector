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
 *
 * MASTER-BRIEF SECTION 9 NAMES THAT AN EXISTING EVENT ALREADY SERVES.
 *
 * Four names in the brief describe signals this file already emits. They were not renamed.
 * A rename has to land on both sides of the allowlist at the same moment, and until the API
 * deploys the new name every beacon 400s and is counted nowhere. It also orphans the history:
 * old rows keep the old name, so a chart of the new name starts at zero and reads as a feature
 * nobody uses. The mapping is written down here instead.
 *
 *   brief name           served by           note
 *   landing_view         page_view           Same event. The path field says which page it was.
 *   grid_survivor_click  card_click          Meta carries the pack id.
 *   pack_row_click       card_click          Same event. Meta already carries the position.
 *   sample_cta_click     sample_cta_clicked  Same event. Only the tense of the name differs.
 *
 * The brief writes a slug where these events carry a pack id. The catalogue is keyed by pack
 * id, so the id is what a join against the catalogue needs. Swapping in a slug would mean a
 * lookup at beacon time and would break the card CTR report that reads these rows today.
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
  | 'faq_helpful'
  // MASTER-BRIEF section 9, the signals nothing else covers. Each one must also be added to
  // AllowedNames in AnalyticsEndpoints.cs or it 400s and is counted nowhere.
  //
  // The discovery instrument. `filter_change` says which control the visitor moved and how
  // many packs were left. `filter_zero_results` says the combination emptied the shelf. The
  // second is not derivable from the first, because a visitor can reach an empty shelf by
  // landing on a filtered link without touching a control.
  | 'filter_change'
  | 'filter_zero_results'
  // The shelf is capped at nine rows with a button that reveals the rest. This counts the
  // press, which is how many readers wanted more than the first page.
  | 'catalogue_page_more'
  // A marketing band scrolled into view. Meta is the band id, so a band can be judged on how
  // many readers reached it rather than on where it sits in the file.
  | 'band_view'
  // The waitlist form was submitted. The placement is not in meta on purpose: WaitlistForm
  // already posts a `source` tag that the waitlist ledger stores, so putting it here would be
  // a second copy of one fact, free to disagree with the first.
  | 'email_submit'
  // How far down the page the reader got. Meta is the threshold as a bare number.
  | 'scroll_depth'
  // A kill-log row was opened. Meta is `<slug>:<cause>`, so the causes readers actually open
  // can be compared against the causes the chart says are biggest.
  | 'kill_row_click'
  // The hero's featured product was clicked. Kept apart from `card_click` because the hero is
  // a different card format, and a click-through rate that mixes formats measures the format
  // rather than the title. The shelf's own CTR report excludes the spotlight for the same
  // reason (see the note on ShelfRows in pages/index.tsx).
  | 'featured_click';

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

/**
 * The one filter dimension whose value is typed by the visitor.
 *
 * Every other discovery control is a fixed set of facet keys, which are safe to send. The
 * search box is free text, and free text a visitor typed is exactly the thing this module
 * must never carry. Its value is reported as `set` or `cleared` instead.
 */
export const FREE_TEXT_FILTER_DIMENSION = 'q';

/**
 * Reduce a facet value to the characters a facet key is allowed to contain.
 *
 * Facet keys are lowercase identifiers, so anything else in the string means the value did not
 * come from the facet list. Replacing rather than dropping keeps the length honest, so a
 * malformed value shows up in the data as a malformed value instead of vanishing.
 */
function safeFacetValue(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
}

/**
 * Build the meta for `filter_change`: `dimension:value:resultCount`.
 *
 * Compact on purpose. This fires on every control the visitor moves, so it is the highest
 * volume event on the page, and three fields in one short string beat a JSON object that
 * spends most of its characters on quotes and braces.
 *
 * `null` means the dimension was cleared, and reads as `any` so a cleared filter and a filter
 * set to a value called "null" cannot be confused.
 */
export function filterChangeMeta(
  dimension: string,
  value: string | number | null,
  resultCount: number,
): string {
  const rendered =
    dimension === FREE_TEXT_FILTER_DIMENSION
      ? value
        ? 'set'
        : 'cleared'
      : value === null || value === ''
        ? 'any'
        : safeFacetValue(String(value));
  return `${safeFacetValue(dimension)}:${rendered}:${resultCount}`;
}

/** One beacon per control the visitor moved. See `filterChangeMeta` for the shape. */
export function trackFilterChange(
  dimension: string,
  value: string | number | null,
  resultCount: number,
): void {
  track('filter_change', filterChangeMeta(dimension, value, resultCount));
}

/**
 * The shelf came back empty. Meta is the names of the dimensions that were constrained,
 * comma separated, so the combinations that fail can be counted.
 *
 * Names only, never values. The search text is a value, and this event exists to learn which
 * controls fight each other, which the names answer on their own.
 */
export function trackFilterZeroResults(dimensions: readonly string[]): void {
  track('filter_zero_results', dimensions.map(safeFacetValue).join(',') || 'none');
}

/** The thresholds `startScrollDepthTracking` reports, in percent of document height. */
export const SCROLL_DEPTH_THRESHOLDS = [25, 50, 75, 100] as const;

/**
 * Report how far down the page the reader got, at most once per threshold per page view.
 *
 * Returns a stop function, so the caller unregisters on unmount. A page view ends when the
 * component unmounts, and the thresholds live in this closure, so a client-side navigation
 * back to the page starts a fresh set rather than staying silent.
 *
 * The listener is passive and the measurement runs inside `requestAnimationFrame`. Scroll
 * fires many times per gesture, and reading `scrollHeight` is a layout read, so measuring on
 * every event would force layout in a tight loop and make the page stutter. One frame is the
 * finest granularity the reader can see anyway.
 *
 * `prefers-reduced-motion` does not gate this. That setting is about animation the page plays
 * at the reader; this measures scrolling the reader did themselves and moves nothing.
 *
 * A page shorter than the viewport counts as fully read. There is nothing to scroll, so the
 * reader has already seen all of it, and reporting nothing would make short pages look
 * abandoned.
 */
export function startScrollDepthTracking(): () => void {
  if (typeof window === 'undefined') return () => {};

  const pending = new Set<number>(SCROLL_DEPTH_THRESHOLDS);
  /* Two variables, not one. The frame id is what cancels a pending callback, and it is assigned
     only after `requestAnimationFrame` returns. A separate flag is set before the call, so the
     throttle is already closed while the callback is being scheduled. Collapsing the two would
     wedge the tracker for good against any implementation that runs the callback synchronously,
     because the id would be written back after the callback had already cleared it. */
  let scheduled = false;
  let frame = 0;

  const stop = (): void => {
    window.removeEventListener('scroll', schedule);
    window.removeEventListener('resize', schedule);
    if (frame) window.cancelAnimationFrame(frame);
    scheduled = false;
    frame = 0;
  };

  const measure = (): void => {
    scheduled = false;
    const height = document.documentElement.scrollHeight;
    const seen = height <= window.innerHeight
      ? 100
      : Math.min(100, ((window.scrollY + window.innerHeight) / height) * 100);
    for (const threshold of SCROLL_DEPTH_THRESHOLDS) {
      if (seen >= threshold && pending.delete(threshold)) {
        track('scroll_depth', String(threshold));
      }
    }
    if (pending.size === 0) stop();
  };

  function schedule(): void {
    if (scheduled) return;
    scheduled = true;
    frame = window.requestAnimationFrame(measure);
  }

  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', schedule, { passive: true });
  // Measure once on mount, on the next frame so the first read happens after layout. A reader
  // who lands on a short page never scrolls, and without this they would report nothing.
  schedule();

  return stop;
}
