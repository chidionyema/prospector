import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { readStylesheet } from '../../__tests__/helpers/stylesheet';

import { allCategories, UNLABELLED } from '../category';
import { SECTOR } from '../facets';

function readSource(relativePath: string): string {
  const path = fileURLToPath(new URL(relativePath, import.meta.url));
  // A stylesheet is read with its local `@import`s inlined; the category tokens moved to
  // `styles/tokens.css` and this guard has to follow them. See `__tests__/helpers/stylesheet.ts`.
  return path.endsWith('.css') ? readStylesheet(path) : readFileSync(path, 'utf8');
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

/**
 * Resolve a token to its literal hex, following `var(--other)` aliases.
 *
 * §3 retuned `--accent` from a literal to `var(--text)` (tokens.css:131, "Ink"). This function
 * matched only `#rrggbb`, so it threw "--accent is not declared" on a token that IS declared, and
 * the failure named the wrong file too. The dangerous version of the same bug is the silent one:
 * had this returned a default instead of throwing, the collision check below would have compared
 * every sector hue against a colour nothing uses, gone green, and stopped guarding `--accent`
 * altogether the day it became an alias. A guard must resolve what the browser resolves.
 */
function token(name: string, seen = new Set<string>()): string {
  if (seen.has(name)) throw new Error(`--${name} is a circular alias`);
  seen.add(name);
  const decl = CSS.match(new RegExp(`--${name}:\\s*([^;]+);`));
  if (!decl) throw new Error(`--${name} is not declared in globals.css or its @imports`);
  const value = decl[1].trim();
  const alias = value.match(/^var\(\s*--([a-z0-9-]+)\s*\)$/);
  if (alias) return token(alias[1], seen);
  const hex = value.match(/^#[0-9A-Fa-f]{6}$/);
  if (!hex) throw new Error(`--${name} resolves to "${value}", which is not a 6-digit hex`);
  return value.toUpperCase();
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
    /*
     * Either binding is accepted because the chip MOVED (2026-08-06). It used to be the first
     * element of the card body, where the local was `cat`; it now sits inside `PackCoverArt`,
     * where the same object arrives as the `category` prop. The move is the fix for a real
     * defect: the chip renders only on a tagged pack, so in a three-up row containing one
     * untagged card that card's title sat ~34px higher than its neighbours' and its price row
     * was pushed down to match. What this test protects is the GUARD, not the identifier -- an
     * ungated chip prints an empty pill on the 9-of-63 untagged packs.
     */
    expect(page, 'the chip must be behind a tagged guard').toMatch(/\{(?:cat|category)\.tagged &&/);
  });

  it('the generated cover branches on `tagged` and draws no mark at all when false', () => {
    expect(page, 'the cover must branch on the flag, not on the icon being present').toMatch(
      /category\.tagged \?/,
    );

    /*
     * THE UNTAGGED BRANCH IS EMPTY. This assertion previously required the opposite -- a
     * `monogram` of the printed heading's initials -- and that requirement is withdrawn, not
     * relaxed, on founder review of the deployed shelf (2026-08-06).
     *
     * The monogram was introduced to solve a real problem correctly identified above: the 9 of 63
     * untagged packs were all drawing `UNLABELLED.icon`, so nine cards wore the same grey
     * briefcase. It was rejected on what it actually rendered. Two capitals at 5.5rem, floating
     * where a product photograph goes, decode to nothing: on the live shelf they read as `HA` and
     * `SE`, which a buyer cannot look up, cannot match to any label on the card, and cannot tell
     * apart from placeholder art or an internal code. The rule this file exists to enforce --
     * "a marker with no name beside it is decoration pretending to be information" -- rules out
     * the monogram by exactly the same argument it rules out the grey briefcase. The monogram
     * merely made the meaningless mark unique per pack instead of shared.
     *
     * The counter-argument on record was that a bare tint "reads as an empty box". That was true
     * when the cover held nothing else, and is no longer true: the cover now carries the spec
     * strip ("8 documents · N sources"), which is information the buyer can act on, in the space
     * the monogram occupied. So the untagged cover is a tint plus real specs, and nothing is
     * drawn that claims a category we do not have.
     *
     * What is still forbidden, and is what this now asserts: drawing `UNLABELLED`'s icon or any
     * other glyph on the untagged branch. The branch must render nothing.
     */
    const cover = page.slice(
      page.indexOf('function PackCoverArt'),
      page.indexOf('function SectorChips'),
    );
    expect(cover.length, 'PackCoverArt must be locatable for this assertion').toBeGreaterThan(0);
    expect(cover, 'the untagged branch must render nothing').toMatch(
      /category\.tagged \?[\s\S]*?\) : null\}/,
    );
    // Comments stripped first: the cover's own docblock explains at length why the monogram was
    // removed, and a rule that forbids naming the thing you removed forbids recording why.
    const coverCode = cover
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
      .replace(/\/\/[^\n]*/g, '');
    expect(coverCode, 'no monogram may come back to the cover').not.toMatch(/monogram/i);
  });

  it('UNLABELLED is still not in the rendered sector vocabulary', () => {
    expect(allCategories().map((c) => c.key)).not.toContain(UNLABELLED.key);
  });
});
