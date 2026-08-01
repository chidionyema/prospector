/**
 * Market resolution and grouping, "boost, don't block" (spec: geo-aware storefront). A visitor
 * from the US should see US-market packs first; every other market, including UK, stays fully
 * reachable underneath. Nothing is ever hidden by market, only reordered.
 *
 * Kept dependency-light and DOM-free, like `discovery.ts`: the resolution order and the
 * grouping rule are pure functions that can be unit-tested without a request object or a
 * browser, and `getServerSideProps` is a thin caller around them.
 *
 * Deliberately NO middleware / no inferred cookie: `Fly-Client-Country` arrives on every
 * request, so geo inference is re-derived fresh each time and nothing is stored on the
 * visitor's device unless they explicitly pick a market (the switcher's `?market=` sets the
 * cookie). Matches the storefront's no-device-storage stance (analytics ships cookieless) and
 * avoids pinning a visitor's first-ever IP guess over their actual current location.
 */

import { marketLabel } from './api/client';

/** Older rows were published before the engine tracked markets at all; treat an absent value
 *  as "uk" everywhere a market is read, resolved, or grouped on, the same rule GET /catalog
 *  applies server-side (Program.cs `?market=` filter) so the two sides can never disagree. */
export const DEFAULT_MARKET = 'uk';

/** Markets the storefront actually has shelves for. `resolveMarket` clamps to this set so an
 *  arbitrary `?market=` / cookie string can never become the resolved market, unclamped it
 *  would empty the main shelf (no pack matches "zz") and flow into a `Set-Cookie` header,
 *  where Node throws on control characters (a crafted URL would 500 the page). */
export const KNOWN_MARKETS: readonly string[] = ['uk', 'us'];

/** The pack shape grouping needs. Structural, like `FacetedPack` in discovery.ts, so a test can
 *  build a two-field fixture without importing the full `Pack` wire type. */
export interface MarketedPack {
  id: string;
  market?: string | null;
}

/** A pack's effective market, applying the null-is-uk rule once, in one place. */
export function packMarket(pack: MarketedPack): string {
  return (pack.market ?? DEFAULT_MARKET).toLowerCase();
}

/**
 * ISO-3166 alpha-2 country code (as seen on the `Fly-Client-Country` request header, both apps
 * run on Fly.io, see next.config.ts for why this is never browser geolocation) -> market code.
 *
 * Only "US" maps away from the default: "boost, don't block" has exactly two shelves to boost
 * between today, and an unrecognised or missing country must fall into the shelf that every pack
 * still shows under, never into a market that does not exist.
 */
export function countryToMarket(country?: string | null): string {
  return (country ?? '').toUpperCase() === 'US' ? 'us' : DEFAULT_MARKET;
}

export interface MarketResolutionInput {
  /** `?market=` on the current request. An explicit override always wins, it is what the
   *  market switcher sends, and a stale inference must never fight a visitor's own click. */
  queryMarket?: string | string[] | null;
  /** The `market` cookie: a stored explicit choice from a previous visit (set ONLY by the
   *  switcher's `?market=`, never inferred). Outranks the header because a visitor travelling
   *  with a VPN or a work laptop keeps the market they picked, not the one their current IP
   *  happens to geolocate to. */
  cookieMarket?: string | null;
  /** Raw `Fly-Client-Country` header value, consulted only when neither of the above is set. */
  countryHeader?: string | null;
}

/**
 * Resolve the market a request should be served: `?market=` override, then the `market` cookie,
 * then the edge-supplied country header, then "uk". Each source is consulted only if the
 * previous one is absent, so an explicit choice always outranks inference. A source whose
 * value is not a KNOWN market is treated as absent (see KNOWN_MARKETS for why), so a
 * hand-edited URL or stale cookie falls through to inference instead of poisoning the shelf.
 */
export function resolveMarket(input: MarketResolutionInput): string {
  const q = Array.isArray(input.queryMarket) ? input.queryMarket[0] : input.queryMarket;
  const query = q?.trim().toLowerCase();
  if (query && KNOWN_MARKETS.includes(query)) return query;
  const cookie = input.cookieMarket?.trim().toLowerCase();
  if (cookie && KNOWN_MARKETS.includes(cookie)) return cookie;
  return countryToMarket(input.countryHeader);
}

/** One "also available" shelf: every pack sharing a market that is not the visitor's resolved
 *  one, grouped so a catalogue that later opens a third market gets its own labelled section
 *  rather than being dumped into a single junk-drawer "other". */
export interface OtherMarketGroup<T extends MarketedPack> {
  market: string;
  label: string;
  packs: T[];
}

export interface GroupedByMarket<T extends MarketedPack> {
  /** Packs in the visitor's resolved market, in the order they were given (the catalogue is
   *  already newest-first from the API; this never re-sorts within a group). */
  matching: T[];
  /** Every other market present, sorted by group size (desc) then market code (asc), the
   *  biggest "also available" shelf leads, and the order is deterministic across renders. */
  others: OtherMarketGroup<T>[];
}

/** Partition packs into the visitor's market and every other, boosting without ever hiding. */
export function groupByMarket<T extends MarketedPack>(
  packs: readonly T[],
  resolvedMarket: string,
): GroupedByMarket<T> {
  const target = resolvedMarket.trim().toLowerCase();
  const matching: T[] = [];
  const otherByMarket = new Map<string, T[]>();

  for (const pack of packs) {
    const m = packMarket(pack);
    if (m === target) {
      matching.push(pack);
      continue;
    }
    const bucket = otherByMarket.get(m);
    if (bucket) bucket.push(pack);
    else otherByMarket.set(m, [pack]);
  }

  const others = Array.from(otherByMarket.entries())
    .map(([market, ps]) => ({ market, label: marketLabel(market), packs: ps }))
    .sort((a, b) => b.packs.length - a.packs.length || a.market.localeCompare(b.market));

  return { matching, others };
}
