import { describe, expect, it } from 'vitest';

import { CARD_META_LIMIT, chunkCardIds } from '@/lib/analytics';

/**
 * The server truncates a beacon's Meta at 512 characters instead of rejecting it
 * (`AnalyticsEndpoints.cs`, `Truncate(request.Meta, 512)`). For a list of pack ids that is
 * the worst possible failure: the payload is not shortened, it is cut into invalid JSON,
 * and every id past the cut is counted nowhere while the beacon still returns 202. Nothing
 * would look broken; the denominator would just be quietly wrong.
 *
 * So the chunking is pinned by a test rather than by arithmetic in a comment.
 */

/** Pack ids on the live shelf are 16 hex characters (e.g. "fbd10d6bdfcd5e31"). */
function packIds(count: number): string[] {
  return Array.from({ length: count }, (_, i) => i.toString(16).padStart(16, 'a'));
}

describe('chunkCardIds', () => {
  it('keeps every chunk inside the server truncation limit', () => {
    // The catalogue renders every pack at once, so this is the real load, not a stress case.
    const chunks = chunkCardIds('0123456789abcdef', packIds(64));

    expect(chunks.length).toBeGreaterThan(1);
    for (const chunk of chunks) {
      expect(chunk.length).toBeLessThanOrEqual(CARD_META_LIMIT);
    }
  });

  it('emits valid JSON carrying the session id in every chunk', () => {
    const chunks = chunkCardIds('sess1234', packIds(64));

    for (const chunk of chunks) {
      const parsed = JSON.parse(chunk) as { s: string; p: string[] };
      expect(parsed.s).toBe('sess1234');
      expect(Array.isArray(parsed.p)).toBe(true);
      expect(parsed.p.length).toBeGreaterThan(0);
    }
  });

  it('loses no card and duplicates none', () => {
    const ids = packIds(64);
    const seen = chunkCardIds('sess1234', ids).flatMap(
      (chunk) => (JSON.parse(chunk) as { p: string[] }).p,
    );

    expect(seen).toHaveLength(ids.length);
    expect(new Set(seen).size).toBe(ids.length);
    expect(seen.sort()).toEqual([...ids].sort());
  });

  it('still emits an id too long to fit on its own', () => {
    // Truncated on the server and therefore partly lost, but a dropped card is worse:
    // it would be silently missing from the denominator.
    const monster = 'z'.repeat(CARD_META_LIMIT * 2);
    const chunks = chunkCardIds('sess1234', [monster]);

    expect(chunks).toHaveLength(1);
    expect(chunks[0]).toContain(monster);
  });

  it('sends nothing when there is nothing to send', () => {
    expect(chunkCardIds('sess1234', [])).toEqual([]);
  });
});
