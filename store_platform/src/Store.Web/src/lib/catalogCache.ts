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

/** Test seam only. Production has no reason to forget a catalogue it successfully fetched. */
export function resetCatalogCache(): void {
  lastGood = null;
}
