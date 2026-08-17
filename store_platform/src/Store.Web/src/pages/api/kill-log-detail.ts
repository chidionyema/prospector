import type { NextApiRequest, NextApiResponse } from 'next';
import { buildKillDetails } from '@/lib/killLog.server';

/**
 * The 371 KB of argument behind /kill-log's four hundred rows, served only to a reader who asks.
 *
 * The page ships every kill's title, cause, date and source COUNT in its own HTML, because those
 * are the four columns of the table and every row is a deep-link anchor. It does not ship the
 * one-liner, the reason or the citation list: those render only inside a row the reader expands,
 * and bundling them cost every visitor a 459 KB JS chunk to display none of it (measured
 * 2026-08-16 -- see the docblock in `lib/killLog.server.ts`). The browser fetches this endpoint
 * once, on the first expand or the first keystroke in the search box.
 *
 * Built once per process and held. The corpus is a build-time JSON import, so it cannot change
 * between requests, and rebuilding the map -- 800 `plainEnglish` passes -- on every fetch would
 * put the work back on the server that was just taken off the client.
 */
let cached: string | null = null;

export default function handler(_req: NextApiRequest, res: NextApiResponse) {
  if (cached === null) cached = JSON.stringify(buildKillDetails());
  // Immutable for a day at the edge: the payload only changes when the site is rebuilt, and a
  // rebuild is a new deployment. `stale-while-revalidate` keeps a stale copy serving instantly
  // while the first request after expiry refreshes it, so no reader waits on a cold cache.
  res.setHeader('Cache-Control', 'public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.status(200).send(cached);
}
