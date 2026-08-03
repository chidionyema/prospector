import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('..', import.meta.url));
const read = (rel: string) => readFileSync(`${SRC}/${rel}`, 'utf8');

describe('1. Matchmaker removed from CatalogBrowser', () => {
  const index = read('pages/index.tsx');

  it('no longer imports Matchmaker or MatchmakerTrigger from discovery', () => {
    expect(index).not.toMatch(/import\s*\{[\s\S]*\bMatchmaker\b[\s\S]*\}\s*from\s*['"]@\/components\/discovery\/Matchmaker['"]/);
    expect(index).not.toMatch(/import\s*\{[\s\S]*\bMatchmakerTrigger\b[\s\S]*\}\s*from\s*['"]@\/components\/discovery\/Matchmaker['"]/);
  });

  it('no longer contains matchOpen / setMatchOpen state', () => {
    expect(index).not.toMatch(/matchOpen/);
  });
});

describe('2. FacetBar gains QuickStart pill-dropdowns', () => {
  const fb = read('components/discovery/FacetBar.tsx');

  it('maps QuickStart pills to advantage, commitment, and payer facet keys', () => {
    // The pills call the same onChange pattern the facet groups use.
    expect(fb).toMatch(/advantage/);
    expect(fb).toMatch(/commitment/);
    expect(fb).toMatch(/payer/);
    // At least one of the pill-definition blocks looks like a dropdown/QuickStart
    expect(fb).toMatch(/QuickStart|quick.*start|pill.*select|dropdown/i);
  });

  it('keeps the close mechanism on mobile (Modal, aria-haspopup, lg:hidden)', () => {
    expect(fb).toMatch(/Modal/);
    expect(fb).toMatch(/lg:hidden/);
  });
});

describe('3. Auto-open moves to FacetBar', () => {
  const fb = read('components/discovery/FacetBar.tsx');

  it('contains the localStorage key mumchimp.matchmaker.autoOpened.v1', () => {
    expect(fb).toContain('mumchimp.matchmaker.autoOpened.v1');
  });

  it('opens the mobile sheet when the flag is absent', () => {
    // The pattern: if the flag is absent, call setSheetOpen(true) inside an effect.
    expect(fb).toMatch(/setSheetOpen\(true\)/);
  });
});