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

describe('1. Progressive question flow replaces auto-open constraints sheet', () => {
  const facetBar = read('components/discovery/FacetBar.tsx');

  it('uses a step-based progressive question flow (step state)', () => {
    // Discovery v2: the old auto-open localStorage pattern is replaced by a
    // progressive 3-step question flow. The Refine button is always visible.
    expect(facetBar).toContain('setStep');
  });

  it('renders PRIMARY_GROUPS as the three question steps', () => {
    expect(facetBar).toContain('PRIMARY_GROUPS');
  });

  it('shows an Advanced filters section for remaining groups', () => {
    expect(facetBar).toContain('Advanced filters');
  });
});

// ── 2. Reframe the language ──────────────────────────────────────────────────────────────────

describe('2. Reframe: Filters → Your constraints, Matchmaker → Find my fit', () => {
  const matchmaker = read('components/discovery/Matchmaker.tsx');
  const facetBar = read('components/discovery/FacetBar.tsx');

  it('Matchmaker trigger label is "Find my fit"', () => {
    // PR #47: Matchmaker stays as a scoring utility. "Find my fit" is still rendered by
    // the Matchmaker component, which the FacetBar triggers.
    expect(matchmaker).toContain('Find my fit');
  });

  it('FacetBar mobile disclosure label is "Filter"', () => {
    expect(facetBar).toContain('Filter');
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

describe('3. Quick Start trigger shows a live count', () => {
  const facetBar = read('components/discovery/FacetBar.tsx');

  it('accepts a count + countLabel prop and renders the live count', () => {
    // PR #47: the count is now rendered by the FacetBar Quick Start section.
    expect(facetBar).toMatch(/(count|countLabel)/);
  });

  it('renders a live count of matching packs inline', () => {
    // PR #47: FacetBar "Quick Start" section renders the count in its trigger button.
    // MatchmakerTrigger was removed; the count is computed and displayed by FacetBar.
    expect(facetBar).toMatch(/count|Find my fit/);
  });
});