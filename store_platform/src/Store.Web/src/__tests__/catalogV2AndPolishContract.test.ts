import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Source-level contract test for the catalog-v2 + polish story
 * (specs/catalog-v2-and-polish-2026-08-01.md).
 *
 * Same convention as the prior contract tests: read each source file as text and assert
 * structural facts the verify chain cannot catch on its own. Each `describe` block
 * corresponds to one numbered item in the spec so a failure points at the spec section,
 * not at a mystery.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const read = (rel: string) => readFileSync(`${SRC}/${rel}`, 'utf8');

// ── Commit 1 — catalog card v2 ──────────────────────────────────────────────────────────────

describe('1.1 PackCard heading is heavier (font-extrabold tracking-tighter)', () => {
  const index = read('pages/index.tsx');

  it('heading class string contains font-extrabold', () => {
    // The h3 in PackCard opens a className through `cx(...)`. The simpler way to verify is to
    // look for the literal token — Tailwind 4 will compile whatever class is used.
    expect(index).toMatch(/<h3[\s\S]*?font-extrabold/);
  });

  it('heading class string contains tracking-tighter', () => {
    expect(index).toMatch(/<h3[\s\S]*?tracking-tighter/);
  });
});

describe('1.2 CTA becomes a ghost button that fills on group-hover', () => {
  const index = read('pages/index.tsx');

  it('PackCard CTA block contains group-hover:bg-primary (the ghost-button fill)', () => {
    expect(index).toMatch(/group-hover:bg-primary/);
  });

  it('PackCard CTA block contains the literal "View blueprint"', () => {
    expect(index).toContain('View blueprint');
  });

  it('CTA is a real <button>, not a <span>', () => {
    // The CTA must be a button (ghost-button pattern). The previous "View blueprint" span was
    // a text link; this must change to <button>.
    const packCardStart = index.indexOf('function PackCard');
    const packCardEnd = index.indexOf('// The hero of the shelf', packCardStart);
    const block = index.slice(packCardStart, packCardEnd);
    expect(block).toMatch(/<button[\s\S]*?View blueprint/);
  });
});

describe('1.3 Evidence row carries the 6/6 check tally', () => {
  const index = read('pages/index.tsx');

  it('ProofLine source contains the literal "6/6" or "6 / 6"', () => {
    expect(index).toMatch(/6\s*\/\s*6/);
  });
});

describe('1.4 Primary chip is colored, others monochrome (PR #49 restored primary accent)', () => {
  const index = read('pages/index.tsx');

  it('primary chip uses bg-primary/10, others are monochrome', () => {
    // PR #49: primary chip (market) restored to bg-primary/10 text-primary for visual
    // hierarchy. All other chips stay monochrome (bg-bg text-muted).
    const fitChipsStart = index.indexOf('function FitChips');
    const fitChipsEnd = index.indexOf('function ProofLine', fitChipsStart);
    const block = index.slice(fitChipsStart, fitChipsEnd);
    // The primary chip class uses bg-primary/10. Other chips must not.
    expect(block).toMatch(/primary.*bg-primary\/10/);
    // Ensure the non-primary path uses bg-bg (monochrome).
    expect(block).toMatch(/bg-bg text-muted/);
  });
});

describe('1.5 Survived seal moves off the cover, sits under the title', () => {
  const index = read('pages/index.tsx');

  it('PackCard does NOT render <SurvivedSeal /> inside <Cover>', () => {
    const packCardStart = index.indexOf('function PackCard');
    const packCardEnd = index.indexOf('// The hero of the shelf', packCardStart);
    const block = index.slice(packCardStart, packCardEnd);
    // Match a SurvivedSeal that lives between <Cover …> and </Cover>. The component is
    // self-closing; the presence of <SurvivedSeal /> inside the Cover children is what we
    // forbid. The simplest invariant: the Cover block in PackCard has no SurvivedSeal.
    expect(block).not.toMatch(/<Cover[\s\S]*?<SurvivedSeal/);
    expect(block).not.toMatch(/<SurvivedSeal[\s\S]*?<\/Cover>/);
  });

  it('PackCard still renders "Survived 6 checks" inside the card body', () => {
    const packCardStart = index.indexOf('function PackCard');
    const packCardEnd = index.indexOf('// The hero of the shelf', packCardStart);
    const block = index.slice(packCardStart, packCardEnd);
    expect(block).toContain('Survived 6 checks');
  });
});

// ── Commit 2 — Tier 1 polish ─────────────────────────────────────────────────────────────────

describe('2.1 Pack detail right rail shows "Survived 6 checks"', () => {
  const page = read('pages/pack/[id].tsx');

  it('the right-rail panel source contains the literal "Survived 6 checks"', () => {
    expect(page).toContain('Survived 6 checks');
  });
});

describe('2.2 Sticky mobile checkout bar on the pack detail page', () => {
  const page = read('pages/pack/[id].tsx');

  it('source contains a fixed bottom-0 or inset-x-0 bottom-0 class', () => {
    expect(page).toMatch(/(fixed|inset-x-0)[^"]*bottom-0/);
  });

  it('source contains lg:hidden (so the bar is mobile-only)', () => {
    // We only assert one lg:hidden pattern in the file. The other lg:hidden usages (the
    // existing right rail's `hidden lg:block`) are unchanged.
    expect(page).toMatch(/lg:hidden/);
  });
});

describe('2.3 "Back to top" floating button on the pack page', () => {
  const page = read('pages/pack/[id].tsx');

  it('source contains the literal "Back to top"', () => {
    expect(page).toContain('Back to top');
  });

  it('source contains a fixed right-4 button', () => {
    expect(page).toMatch(/fixed[^"]*right-4/);
  });
});

describe('2.4 DossierCard shared by SimilarPacks and PackGrid', () => {
  it('components/discovery/DossierCard.tsx exists and exports DossierCard', () => {
    const comp = read('components/discovery/DossierCard.tsx');
    expect(comp).toMatch(/export\s+function\s+DossierCard/);
  });

  it('SimilarPacks imports and uses DossierCard inside the <li>', () => {
    const comp = read('components/discovery/SimilarPacks.tsx');
    expect(comp).toMatch(/import[\s\S]*?DossierCard/);
    expect(comp).toMatch(/<DossierCard/);
  });

  it('PackGrid imports and uses DossierCard inside the <li>', () => {
    const comp = read('components/discovery/PackGrid.tsx');
    expect(comp).toMatch(/import[\s\S]*?DossierCard/);
    expect(comp).toMatch(/<DossierCard/);
  });
});

// ── Commit 3 — Tier 2 polish ─────────────────────────────────────────────────────────────────

describe('3.1 Matchmaker progress + revise link', () => {
  const m = read('components/discovery/Matchmaker.tsx');

  it('source contains a "Step N of 3" indicator', () => {
    expect(m).toMatch(/Step\s+\d+\s+of\s+3/i);
  });

  it('source contains a "Revise answers" affordance', () => {
    expect(m).toContain('Revise answers');
  });
});

describe('3.2 CommandPalette ↵ hint on the active row', () => {
  const cp = read('components/discovery/CommandPalette.tsx');

  it('source contains a <kbd>↵</kbd> (or the unicode arrow) tied to the active row', () => {
    expect(cp).toMatch(/<kbd[^>]*>\s*↵\s*<\/kbd>/);
  });
});

describe('3.3 Empty waitlist state has a "Reset all filters" button', () => {
  const es = read('components/discovery/EmptyState.tsx');

  it('DiscoveryWaitlist source contains "Reset all filters"', () => {
    expect(es).toContain('Reset all filters');
  });

  it('pages/index.tsx wires a reset callback into the empty state', () => {
    // The reset callback fires only when the filter state is non-empty; the index page
    // already passes `apply` (the state setter) into the empty-state family. We assert
    // that the DiscoveryWaitlist call site passes a callback that clears the state.
    const index = read('pages/index.tsx');
    expect(index).toMatch(/<DiscoveryWaitlist[^>]*?(?:onReset|clearAll|reset)/);
  });
});

describe('3.4 Near-miss chips become the relaxer (button instead of <li>)', () => {
  const es = read('components/discovery/EmptyState.tsx');

  it('the candidate <li> in DiscoveryNearMiss is actually a <button>', () => {
    // The candidates list renders each miss as a clickable chip. The spec converts <li> chips
    // into <button>s that call onRelax(relaxedState). We assert that the marker text
    // `candidate.pack.title` is wrapped in a <button>.
    expect(es).toMatch(/<button[\s\S]*?candidate\.pack\.title/);
  });
});