import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

function existsRelative(relativePath: string): boolean {
  return existsSync(fileURLToPath(new URL(relativePath, import.meta.url)));
}

/**
 * N1 — Persistence of trust.
 *
 * The audit (§4.13) found the trust facts scattered across the page in
 * different shapes: the £49 price in the hero, the cards, and the CtaBand;
 * the 14-day refund in the trust pills, the pack detail, and the
 * comparison block; the 1,080 killed in the heartbeat. The buyer was
 * told the same thing five times in five different shapes.
 *
 * The fix is a single "Trust & guarantees" row above the CtaBand on the
 * home page. Five facts in one place: £49 once, 14 day refund, 1,968
 * researched, 1,080 killed, 61 live. The row is the only place these
 * facts live; everywhere else links to it.
 */
describe('N1 — Persistence of trust', () => {
  const trustRowExists = existsRelative('../components/marketing/TrustGuaranteesRow.tsx');
  const page = readSource('../pages/index.tsx');

  it('declares a TrustGuaranteesRow component', () => {
    expect(
      trustRowExists,
      'components/marketing/TrustGuaranteesRow.tsx must exist',
    ).toBe(true);
  });

  it('TrustGuaranteesRow renders all five trust facts', () => {
    if (!trustRowExists) return;
    const source = readSource('../components/marketing/TrustGuaranteesRow.tsx');
    // The five facts: £49 once, 14 day refund, 1,968 researched,
    // 1,080 killed, 61 live. The component must reference each.
    /*
     * Was `/£49|GBP 49|\$\{?49|\b49\b/`. `\b49\b` matches any 49 anywhere in the file including
     * a comment, so once the ladder shipped and a comment explained the old price, this assertion
     * was green against a component that no longer rendered one. The fact still has to be there;
     * what changed is that it is now a prop the caller computes from the live packs, and the
     * literal is what must NOT be there.
     */
    const hasPrice = /price\.label|'One payment'/.test(source);
    const strippedSource = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    expect(
      strippedSource.match(/£\s?\d+/g) ?? [],
      'the trust row must not hardcode a price',
    ).toEqual([]);
    const hasRefund = /14\s*day|refund/i.test(source);
    const hasResearched = /1,?968|researched/i.test(source);
    const hasKilled = /1,?080|killed/i.test(source);
    const hasLive = /\b61\b|live/i.test(source);
    expect(hasPrice, 'TrustGuaranteesRow must render the price fact').toBe(true);
    expect(hasRefund, 'TrustGuaranteesRow must render the 14 day refund').toBe(true);
    expect(hasResearched, 'TrustGuaranteesRow must render the researched count').toBe(true);
    expect(hasKilled, 'TrustGuaranteesRow must render the killed count').toBe(true);
    expect(hasLive, 'TrustGuaranteesRow must render the live count').toBe(true);
  });

  it('TrustGuaranteesRow sources counts from killTotals, not hardcoded', () => {
    // The audit: "The component must use the existing killTotals data so the
    // counts stay in sync with the kill log." A hardcoded "1,080" is a
    // contract violation.
    if (!trustRowExists) return;
    const source = readSource('../components/marketing/TrustGuaranteesRow.tsx');
    const usesKillTotals = /killTotals|killed.*passed|from ['"]@\/data\/kill-log-totals['"]/.test(source);
    expect(
      usesKillTotals,
      'TrustGuaranteesRow must import killTotals (not hardcode the numbers)',
    ).toBe(true);
  });

  it('home page renders TrustGuaranteesRow above the CtaBand', () => {
    // The audit: "a single 'Trust & guarantees' row above the CtaBand."
    // The row must come before <CtaBand in the source. The JSX usage is
    // `<TrustGuaranteesRow />` (with the leading `<`), so we look for that
    // rather than the import statement which would also match.
    if (!trustRowExists) return;
    const trustRowIdx = page.indexOf('<TrustGuaranteesRow');
    const ctaBandIdx = page.indexOf('<CtaBand');
    expect(
      trustRowIdx > 0 && ctaBandIdx > 0 && trustRowIdx < ctaBandIdx,
      'index.tsx must render <TrustGuaranteesRow> above <CtaBand>',
    ).toBe(true);
  });

  /*
   * Regression: the home page rendered its live count twice, from two sources.
   *
   * `index.tsx` reads `stats.listed` off the live `GET /catalog`; this row read
   * `kill-log-totals.json`, which is frozen at build time. Measured 2026-08-05 on the
   * production build: the live catalog held 61 packs, `kill-log-totals.json` said
   * `"shown": 60`, and the rendered home page carried the strings "61 live now, of 80
   * that reached final packaging" AND "60 live now". Every pack published without a
   * redeploy widens the gap, and a storefront whose position is "every claim is backed
   * by a source you can open" cannot contradict itself in its own shop window.
   *
   * The fix is a `listed` prop fed from the live stats. The snapshot survives only as
   * the fallback for callers with no live figure to hand.
   */
  describe('the live count comes from the live stats, not the build-time snapshot', () => {
    it('TrustGuaranteesRow accepts a listed prop and prefers it over the snapshot', () => {
      if (!trustRowExists) return;
      const source = readSource('../components/marketing/TrustGuaranteesRow.tsx');
      expect(source, 'must accept a `listed` prop').toMatch(/listed\??\s*:\s*number/);
      expect(
        source,
        'the live figure must prefer `listed` and fall back to the snapshot, not the reverse',
      ).toMatch(/const\s+live\s*=\s*listed\s*\?\?/);
    });

    it('the home page feeds it the live stats figure', () => {
      if (!trustRowExists) return;
      expect(
        page,
        'index.tsx must pass the live `stats.listed` into <TrustGuaranteesRow>',
      ).toMatch(/<TrustGuaranteesRow[^>]*listed=\{stats\??\.listed\}/);
    });
  });
});
