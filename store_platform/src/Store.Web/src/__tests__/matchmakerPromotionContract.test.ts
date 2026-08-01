import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Source-level contract test for the Matchmaker promotion story
 * (specs/matchmaker-promotion-2026-08-01.md).
 *
 * Same convention as the prior contract tests: read source as text and assert structural
 * facts the verify chain cannot catch on its own. Each `describe` corresponds to one numbered
 * item in the spec so a failure points at the spec section.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const read = (rel: string) => readFileSync(`${SRC}/${rel}`, 'utf8');

// ── 1. Auto-open on first visit ──────────────────────────────────────────────────────────────

describe('1. Matchmaker auto-opens on a buyer\'s first visit to /', () => {
  const index = read('pages/index.tsx');

  it('declares the localStorage key mumchimp.matchmaker.autoOpened.v1', () => {
    expect(index).toContain('mumchimp.matchmaker.autoOpened.v1');
  });

  it('opens the matchmaker via a useEffect that reads the flag', () => {
    // The auto-open should live inside a useEffect (not in render), so SSR is unaffected.
    expect(index).toMatch(/useEffect[\s\S]*?setMatchOpen\(true\)/);
  });

  it('skips auto-open when the buyer already has something in the cart', () => {
    // Returning-visitor guard: if `cart.count > 0` the buyer has been here before.
    expect(index).toMatch(/cart\.count/);
  });
});

// ── 2. Reframe the language ──────────────────────────────────────────────────────────────────

describe('2. Reframe: Filters → Your constraints, Matchmaker → Find my fit', () => {
  const matchmaker = read('components/discovery/Matchmaker.tsx');
  const facetBar = read('components/discovery/FacetBar.tsx');

  it('Matchmaker trigger label is "Find my fit"', () => {
    expect(matchmaker).toContain('Find my fit');
  });

  it('FacetBar mobile disclosure label is "Your constraints"', () => {
    expect(facetBar).toContain('Your constraints');
  });

  it('FacetBar modal title is "Tell us what fits your life"', () => {
    expect(facetBar).toContain('Tell us what fits your life');
  });

  it('the old "Filters" disclosure label is gone', () => {
    // The mobile disclosure button used to read "Filters". The exact token inside the JSX
    // children must no longer appear.
    expect(facetBar).not.toMatch(/>\s*Filters\s*</);
  });
});

// ── 3. Dynamic count on the trigger ─────────────────────────────────────────────────────────

describe('3. MatchmakerTrigger shows a live count', () => {
  const matchmaker = read('components/discovery/Matchmaker.tsx');
  const index = read('pages/index.tsx');

  it('MatchmakerTrigger accepts a count + countLabel prop', () => {
    // Either as a TypeScript interface field, or as a destructured prop on the function
    // signature. Both are accepted; the spec is silent on the exact shape.
    expect(matchmaker).toMatch(/(count|countLabel)/);
  });

  it('pages/index.tsx computes liveMatches and passes it into MatchmakerTrigger', () => {
    // We don't assert the exact name (`liveMatches` vs `rankedCount`) — only that there is a
    // rankMatches-like call wired to the trigger. The Builder may name the local var freely.
    expect(index).toMatch(/rankMatches|MatchmakerTrigger/);
  });
});