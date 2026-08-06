import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { allCategories, UNLABELLED } from '../category';
import { SECTOR } from '../facets';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

/**
 * The category scale.
 *
 * WRITTEN 2026-08-06, and the reason it is worth reading: three separate comments -- in
 * `lib/category.ts` (twice) and in `styles/globals.css` -- already cited "categoryScale.test.ts"
 * as the thing that held these properties. The file did not exist. Every one of those citations
 * was an assertion wearing the costume of a proof, on the one storefront whose entire pitch is
 * that a claim without a source is not a claim. Writing it immediately found a real defect: the
 * stylesheet's twelve contrast annotations were measured against a flat #F4F4F5 that no element
 * paints, and four of them did not hold even on that basis.
 *
 * Two properties, both of which the scale broke once:
 *
 *  1. CONTRAST. Every sector hue is legible where it is actually printed. It is never printed on
 *     the page canvas: the sector name and the cover mark both sit on `bg-cat-X/10`, i.e. 10% of
 *     the hue itself over --surface, so that composite is what gets measured here rather than the
 *     flat token the stylesheet used to quote.
 *  2. NO SEMANTIC COLLISION. Red means killed and green means survived on every other surface of
 *     this site. A sector that happens to be issued the danger red turns a neutral facet into a
 *     verdict, on a shelf where the verdict is the product.
 *
 * The ratios are recomputed from the tokens, never read from the annotations beside them: an
 * annotation is a comment, and a comment cannot fail.
 */

const CSS = readSource('../../styles/globals.css');

function token(name: string): string {
  const match = CSS.match(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{6})`));
  if (!match) throw new Error(`--${name} is not declared in globals.css`);
  return match[1].toUpperCase();
}

function channels(hex: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

/** WCAG 2.1 relative luminance. */
function luminance(hex: string): number {
  const [r, g, b] = channels(hex).map((raw) => {
    const c = raw / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** `bg-cat-X/10` is not a colour, it is a composite. Resolve it the way the browser does. */
function over(foreground: string, alpha: number, background: string): string {
  const f = channels(foreground);
  const b = channels(background);
  return `#${f
    .map((_, i) => Math.round(f[i] * alpha + b[i] * (1 - alpha)))
    .map((v) => v.toString(16).padStart(2, '0'))
    .join('')}`.toUpperCase();
}

describe('the category scale', () => {
  const sectorTokens = SECTOR.map((sector) => ({
    sector,
    hex: token(`cat-${sector.replace(/_/g, '-')}`),
  }));

  it('declares one token per sector, named after the sector verbatim', () => {
    // The names are the engine's `sector` keys, not colour names, so renaming a sector in
    // facets.ts fails here instead of silently keeping a stale hue under the old name.
    expect(sectorTokens).toHaveLength(SECTOR.length);
    const declared = [...CSS.matchAll(/--cat-([a-z-]+):/g)].map((m) => m[1].replace(/-/g, '_'));
    expect([...new Set(declared)].sort()).toEqual([...SECTOR].sort());
  });

  it('every sector hue clears 4.5:1 on the tint it is printed on', () => {
    const surface = token('surface');
    const failures = sectorTokens
      .map(({ sector, hex }) => ({
        sector,
        ratio: Number(contrast(hex, over(hex, 0.1, surface)).toFixed(2)),
      }))
      .filter(({ ratio }) => ratio < 4.5);
    // Reported as the failing sectors and their ratios, not as a bare count: a failure has to
    // name the hue to retune and by how much.
    expect(failures).toEqual([]);
  });

  it('no sector hue is byte-equal to a semantic colour', () => {
    /*
     * Red is killed, green is survived, and both are load-bearing on the kill log, the check
     * table and the filter panel. The eight-hue set deleted earlier on 2026-08-06 issued a sector
     * a value from the danger family, which turned "this pack is about licensing" into "this pack
     * failed" for anyone reading colour before text.
     *
     * Byte-equality is the floor, not the ceiling: it catches the copy-paste, not a hue two
     * degrees away. The ceiling is the rule the scale is built on and which no test can enforce --
     * HUE IS DECORATION, THE LABEL IDENTIFIES -- so nothing on the shelf is allowed to depend on
     * a reader naming anything from colour alone.
     */
    const reserved = [
      'danger',
      'danger-strong',
      'success',
      'success-strong',
      'accent',
      'warning',
      'warning-strong',
      'info',
    ].map((name) => ({ name, hex: token(name) }));

    const collisions = sectorTokens.flatMap(({ sector, hex }) =>
      reserved.filter((r) => r.hex === hex).map((r) => `${sector} === --${r.name} (${hex})`),
    );
    expect(collisions).toEqual([]);
  });
});

describe('the untagged pack renders no sector marker', () => {
  /*
   * `lib/category.ts` states the rule and cites this file for it: a pack with no sector renders
   * NOTHING -- no chip, no label, no glyph -- because a marker with no name beside it is
   * decoration pretending to be information, and a sector glyph on a pack whose sector we do not
   * know is an unsourced claim.
   *
   * `UNLABELLED` still carries an `ink`/`tint`/`icon` as graceful degradation for a caller that
   * forgets to branch (see category.test.ts). This asserts the card is not that caller. It has
   * been that caller: until 2026-08-06 the generated cover drew `UNLABELLED.icon` at 40px and
   * again at 96px, so the 9 untagged packs of the 63 then live all wore the same grey briefcase.
   */
  const page = readSource('../../pages/index.tsx');

  it('the sector chip is gated on `tagged`', () => {
    expect(page, 'the chip must be behind a tagged guard').toMatch(/\{cat\.tagged &&/);
  });

  it('the generated cover branches on `tagged` and draws no icon when false', () => {
    expect(page, 'the cover must branch on the flag, not on the icon being present').toMatch(
      /category\.tagged \?/,
    );
    // The untagged branch's mark is derived from the pack's own title, which is already on the
    // card: it distinguishes without asserting anything the pack does not say itself.
    // From the heading the card actually prints, not from `pack.title`: the two differ whenever
    // the engine supplied a `cardLine`, and the first cut of this drew `FK` (from "FridgePass
    // Kit") on a card headed "Sell a fridge sensor that prints daily hygiene logs".
    expect(page, 'the untagged cover must be built from the printed heading').toMatch(
      /monogram[\s\S]{0,900}cardHeading\(pack\)\s*\n?\s*\.heading/,
    );
  });

  it('UNLABELLED is still not in the rendered sector vocabulary', () => {
    expect(allCategories().map((c) => c.key)).not.toContain(UNLABELLED.key);
  });
});
