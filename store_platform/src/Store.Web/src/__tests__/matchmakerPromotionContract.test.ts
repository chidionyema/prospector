import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Source-level contract test for the Matchmaker promotion story
 * (specs/matchmaker-promotion-2026-08-01.md).
 *
 * UPDATED 2026-08-02 for unified-your-fit: the auto-open and Matchmaker widget
 * were merged into FacetBar. This test now asserts the surviving labels and the
 * relocated auto-open logic.
 *
 * Same convention as the prior contract tests: read source as text and assert structural
 * facts the verify chain cannot catch on its own. Each `describe` corresponds to one numbered
 * item in the spec so a failure points at the spec section.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const read = (rel: string) => readFileSync(`${SRC}/${rel}`, 'utf8');

// ── 1. Auto-open on first visit (moved to FacetBar) ─────────────────────────────────────────

describe('1. Auto-open on first visit lives in FacetBar', () => {
  const fb = read('components/discovery/FacetBar.tsx');

  it('declares the localStorage key mumchimp.matchmaker.autoOpened.v1', () => {
    expect(fb).toContain('mumchimp.matchmaker.autoOpened.v1');
  });

  it('opens the mobile sheet via useEffect when the flag is absent', () => {
    expect(fb).toMatch(/useEffect[\s\S]*?setSheetOpen\(true\)/);
  });

  it('skips auto-open when the buyer already has something in the cart', () => {
    expect(fb).toMatch(/cart\.count/);
  });
});

// ── 2. Reframe: Filters → Your constraints, Matchmaker → Find my fit ────────────────────────

describe('2. Labels survive the unification', () => {
  const matchmaker = read('components/discovery/Matchmaker.tsx');
  const facetBar = read('components/discovery/FacetBar.tsx');

  it('Matchmaker still contains "Find my fit" (scoring utility preserved)', () => {
    expect(matchmaker).toContain('Find my fit');
  });

  it('FacetBar mobile disclosure label is "Your constraints"', () => {
    expect(facetBar).toContain('Your constraints');
  });

  it('FacetBar modal title is "Tell us what fits your life"', () => {
    expect(facetBar).toContain('Tell us what fits your life');
  });

  it('the old "Filters" disclosure label is gone', () => {
    expect(facetBar).not.toMatch(/>\s*Filters\s*</);
  });
});

// ── 3. QuickStart pills replace the MatchmakerTrigger count ─────────────────────────────────

describe('3. QuickStart pills in FacetBar replace MatchmakerTrigger', () => {
  const fb = read('components/discovery/FacetBar.tsx');

  it('FacetBar renders QuickStart pills for skills, time, and payer', () => {
    expect(fb).toMatch(/QuickStart|quick.*start|My skills/);
  });

  it('QuickStart pills map to advantage, commitment, and payer facet keys', () => {
    expect(fb).toMatch(/advantage/);
    expect(fb).toMatch(/commitment/);
    expect(fb).toMatch(/payer/);
  });
});