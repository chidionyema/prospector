import type { CatalogStats, Pack } from '@/lib/api/client';

/**
 * Last-known-good catalogue, held in module scope on the Next.js server.
 *
 * The defect this exists for: `getServerSideProps` caught ANY catalogue failure and returned
 * `packs: []`, which the shelf renders as "No packs are live right now." That sentence is a claim
 * about the BUSINESS -- we have nothing to sell -- produced by an outage on our own side. It is the
 * same shape as the engine's rule that a failed verdict call must DEFER rather than contribute an
 * `unverifiable` check: a call that did not complete is not evidence of anything.
 *
 * So a fetch failure now serves the last catalogue we actually saw, and only a cold machine that
 * has never had one falls through to an honest "we can't reach the catalogue" state.
 *
 * Deliberately module scope and not a shared cache: it survives exactly as long as the Node
 * process, which is the same lifetime as the outage it covers. A stale shelf for the minutes an
 * API deploy takes is strictly better than a false sold-out, and a machine that restarts loses
 * the cache and tells the truth instead of guessing.
 */
export interface CachedCatalog {
  packs: Pack[];
  stats: CatalogStats | null;
  /** When this was fetched, as epoch ms. Callers use it to label staleness, never to expire it. */
  fetchedAt: number;
}

let lastGood: CachedCatalog | null = null;

/** Record a SUCCESSFUL fetch. Never called on the failure path -- that is the whole point. */
export function rememberCatalog(packs: Pack[], stats: CatalogStats | null): void {
  lastGood = { packs, stats, fetchedAt: Date.now() };
}

/** The last catalogue actually retrieved, or null if this process has never had one. */
export function lastKnownCatalog(): CachedCatalog | null {
  return lastGood;
}

/**
 * How long a catalogue counts as CURRENT, not merely last-known-good.
 *
 * Measured 2026-08-16 against the live API: `GET /catalog` takes 0.37-0.48s and `/catalog/stats`
 * 0.36s, and the home page awaits both inside `getServerSideProps` -- so every visitor waited
 * roughly half a second before the first byte of HTML left the server (live TTFB on
 * https://mumchimp.com/: 0.495s). Nothing about that call is per-visitor: the identical catalogue
 * is fetched again for the next arrival.
 *
 * Sixty seconds is chosen against what the staleness actually costs. The engine publishes a pack
 * at most a few times a day, so the window's realistic effect is a newly listed pack appearing up
 * to a minute late -- the same order of lateness /kill-log already accepts with its 300s ISR
 * revalidate. A price change is the one edit where staleness would matter, and the money rail does
 * not read this cache: checkout re-reads the pack, so a stale shelf cannot mis-charge anyone.
 */
export const CATALOG_FRESH_MS = 60_000;

/**
 * The catalogue if it was fetched recently enough to serve without asking again, else null.
 *
 * Distinct from `lastKnownCatalog`, and the two must not be merged: that one answers "what is the
 * best thing I can show during an outage" and has no expiry BY DESIGN, this one answers "can I
 * skip the round trip". A caller that confused them would either serve a six-hour-old shelf as
 * current, or refuse to serve anything during exactly the outage the other function exists for.
 */
export function freshCatalog(now: number = Date.now()): CachedCatalog | null {
  if (!lastGood) return null;
  return now - lastGood.fetchedAt < CATALOG_FRESH_MS ? lastGood : null;
}

/** Test seam only. Production has no reason to forget a catalogue it successfully fetched. */
export function resetCatalogCache(): void {
  lastGood = null;
}
