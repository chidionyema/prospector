import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * Shop-card wrap and thumbnail. Founder, 2026-09-01, on wrapping and images, then the whole
 * site starting at the landing page. These pins live here, not in the suspended appearance
 * suite, because unclamping the drawing, clipping the cover bleed, and stretching the tile
 * description are the defects that made the cards look unfinished.
 */
describe('shop card wrap and thumbnail', () => {
  const globals = readFileSync(fileURLToPath(new URL('../styles/globals.css', import.meta.url)), 'utf8');
  const stripped = globals.replace(/\/\*[\s\S]*?\*\//g, '');

  it('does not unclamp the drawing\'s row and tile descriptions', () => {
    expect(stripped).not.toMatch(/-webkit-line-clamp:\s*none/);
  });

  it('gives the text column a shrinkable track next to the thumbnail', () => {
    expect(stripped).toMatch(/grid-template-columns:\s*112px minmax\(0,\s*1fr\) auto/);
  });

  it('uses a square row thumbnail instead of a 16:9 postage stamp', () => {
    expect(stripped).toMatch(/\.rowcover\s*\{[^}]*aspect-ratio:\s*1\s*\/\s*1/);
    expect(stripped).not.toMatch(/\.rowcover\s*\{[^}]*aspect-ratio:\s*16\s*\/\s*9/);
  });

  it('keeps the phone thumbnail beside the text, not a full-width band', () => {
    expect(stripped).not.toMatch(/\.rowcover\s*\{[^}]*grid-column:\s*1\s*\/\s*-1);
    expect(stripped).toMatch(/grid-template-columns:\s*72px minmax\(0,\s*1fr\) auto/);
  });

  it('lets the tile cover bleed past Tailwind\'s img max-width', () => {
    expect(stripped).toMatch(/\.htile \.cover\s*\{[^}]*max-width:\s*none);
  });

  it('does not stretch the tile description to fill the card', () => {
    expect(stripped).toMatch(/\.htile p\s*\{[^}]*flex:\s*none);
  });

  it('gives the featured pack a picture, same as the tiles and rows', () => {
    expect(stripped).toMatch(/\.featured:has\(> \.cover\)/);
  });

  it('places the featured picture as a plate, not a stretch-span', () => {
    expect(stripped).toMatch(/\.featured:has\(> \.cover\) > \.cover\s*\{[^}]*aspect-ratio:\s*4 \/ 3);
    expect(stripped).not.toMatch(/grid-row:\s*1 \/ span 8/);
    expect(stripped).not.toMatch(/min-height:\s*280px/);
  });

  it('puts the hero product in one column so 6 in 100 sits on the card grid', () => {
    expect(stripped).toMatch(/\.hero \.featured:has\(> \.cover\)\s*\{[^}]*grid-template-areas:);
    expect(stripped).toMatch(/\.featured \.ratiofig\s*\{[^}]*font-size:\s*28px);
  });

  it('lets a pack-page title use the column, not the landing slogan measure', () => {
    expect(stripped).toMatch(/\.two h1\s*\{[^}]*max-width:\s*none);
  });
});
