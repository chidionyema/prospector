import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

import { OG, OG_TOKEN_OF } from '@/lib/design/ogPalette';

/**
 * The share card is drawn by Satori, which resolves no CSS custom properties, so its colours are
 * literal hexes. This is what stops those literals drifting from the tokens they copy -- which they
 * had already done, in four values out of five, including the survive green.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
// COMMENTS STRIPPED FIRST. tokens.css argues its case in prose beside every value, and those
// comments contain colons and semicolons; without this, `--surface2: #FAFAFA;` lost to a sentence
// further down the file that merely mentioned the name, and the test reported the token had
// "moved to" a fragment of English.
const TOKENS = readFileSync(join(SRC, 'styles/tokens.css'), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
);

/**
 * The value of a token, following `var()` to the end of the chain.
 *
 * Takes the LAST declaration of a name, because tokens.css redeclares under media and theme
 * blocks and the last one is what a fresh light-mode document computes -- which is what the card
 * renders against.
 */
function resolve(token: string, seen = new Set<string>()): string {
  expect(seen.has(token), `circular token chain at ${token}`).toBe(false);
  seen.add(token);
  const decls = [...TOKENS.matchAll(new RegExp(`(?:^|[;{\\s])${token}\\s*:\\s*([^;]+);`, 'g'))];
  expect(decls.length, `${token} is not declared in tokens.css`).toBeGreaterThan(0);
  const value = decls[decls.length - 1][1].trim();
  const chained = value.match(/^var\(\s*(--[a-z0-9-]+)\s*\)$/i);
  return chained ? resolve(chained[1], seen) : value;
}

describe('the share card mirrors the tokens exactly', () => {
  for (const [key, token] of Object.entries(OG_TOKEN_OF)) {
    it(`OG.${key} still equals ${token}`, () => {
      const actual = resolve(token).toUpperCase();
      expect(
        OG[key as keyof typeof OG].toUpperCase(),
        `${token} moved to ${actual}. Update OG.${key} in lib/design/ogPalette.ts -- Satori cannot ` +
          'read the stylesheet, so this copy is the card and nothing else will catch it.',
      ).toBe(actual);
    });
  }

  it('names a token for every colour except the one that has none', () => {
    // A value added to OG without a row in OG_TOKEN_OF is an unchecked literal, which is the exact
    // thing this file exists to prevent.
    const unchecked = Object.keys(OG).filter((k) => !(k in OG_TOKEN_OF));
    expect(unchecked).toEqual(['onInk']);
  });

  it('is imported by the share card and by nothing else', () => {
    // The rest of the site reads tokens through Tailwind, where the browser resolves them. A second
    // importer would be a literal hex used where a token would have worked.
    const card = readFileSync(join(SRC, 'pages/og/pack/[id].tsx'), 'utf8');
    expect(card).toContain("from '@/lib/design/ogPalette'");
  });
});
