import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * Shop-card wrap and thumbnail. Founder, 2026-09-01, on /packs and the home cards:
 * wrapping and images look rubbish. These pins live here, not in the suspended appearance
 * suite, because unclamping the drawing and shrinking the cover to a 16:9 postage stamp
 * are the two defects that made the cards look unfinished.
 */
describe('shop card wrap and thumbnail', () => {
  const globals = readFileSync(fileURLToPath(new URL('../styles/globals.css', import.meta.url)), 'utf8');
  const stripped = globals.replace(/\/\*[\s\S]*?\*\//g, '');

  it('does not unclamp the drawing\'s row and tile descriptions', () => {
    expect(stripped).not.toMatch(/-webkit-line-clamp:\s*none/);
  });

  it('gives the text column a shrinkable track next to the thumbnail', () => {
    expect(stripped).toMatch(/grid-template-columns:\s*96px minmax\(0,\s*1fr\) auto/);
  });

  it('uses a square row thumbnail instead of a 16:9 postage stamp', () => {
    expect(stripped).toMatch(/\.rowcover\s*\{[^}]*aspect-ratio:\s*1\s*\/\s*1/);
    expect(stripped).not.toMatch(/\.rowcover\s*\{[^}]*aspect-ratio:\s*16\s*\/\s*9/);
  });

  it('keeps the phone thumbnail beside the text, not a full-width band', () => {
    expect(stripped).not.toMatch(/\.rowcover\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/);
    expect(stripped).toMatch(/grid-template-columns:\s*64px minmax\(0,\s*1fr\) auto/);
  });
});
