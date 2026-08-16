import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { readStylesheet } from '../../__tests__/helpers/stylesheet';

import type { Pack } from '../api/client';
import { allCategories, UNLABELLED } from '../category';
import { SECTOR } from '../facets';
import { packLeadStat } from '../packStat';

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
     *
     * `?` joins `&&` as an accepted spelling (2026-08-15). Two call sites now hand the label to
     * the shared `PackCardHeader` as a prop (`cat.tagged ? cat.label : null`) and the row hands
     * its own branch a DELIBERATE empty placeholder, so the guard is a ternary in three of the
     * four places it appears. What this test protects has never been the operator -- it is that
     * no code path can reach the chip with an untagged category.
     */
    expect(page, 'the chip must be behind a tagged guard').toMatch(
      /\{(?:cat|category)\.tagged (?:&&|\?)/,
    );

    /*
     * THE ROW'S EMPTY PLACEHOLDER IS GONE, AND SO IS THE THING IT HELD OPEN (2026-08-16).
     *
     * It was a `hidden flex-none sm:block sm:w-44` span with `aria-hidden`, and its only job was
     * to keep the sector column open on an untagged pack so that the lead figure printed beside
     * it landed on the same x as every other row's.
     *
     * The figure is not on that line any more. It moved under the price, into a fixed-width
     * value column, because the price and the multiple are the two numbers a buyer weighs
     * against each other. So there is nothing left beside the sector to align, and an 11rem
     * empty column on an untagged row is now just a hole in the meta line.
     *
     * What replaces the promise is stronger, because it no longer depends on the sector: the
     * value column is a FIXED width, so the price and the figure land on the same x whether or
     * not the pack carries a sector at all. That is what is pinned here instead.
     */
    const rowStart = page.indexOf("if (weight === 'row') {", page.indexOf('function PackCard('));
    expect(rowStart, "PackCard's row branch must be locatable").toBeGreaterThan(-1);
    const row = page.slice(rowStart, page.indexOf('\n  }', rowStart));
    expect(row, 'the row must not re-open an empty sector column').not.toMatch(/sm:w-44/);
    expect(
      row,
      'the value column must be a fixed width, so the price lands on the same x on every row',
    ).toMatch(/className="flex w-\d+ flex-none flex-col items-end text-right sm:w-\d+"/);
  });

  it('the card draws no marker for a missing sector, and is not empty without one', () => {
    /*
     * REWRITTEN 2026-08-14. This assertion used to locate `function PackCoverArt` and require its
     * untagged branch to render `category.tagged ? category.label : null`. The cover is deleted --
     * a 112px plate reading as a failed image load, carrying a mark computed by hashing the pack
     * id -- so the old locator matches nothing and the old spelling exists nowhere.
     *
     * THE RULE IS UNCHANGED and is what is re-pinned below: "a marker with no name beside it is
     * decoration pretending to be information", so a pack whose sector we do not know draws
     * NOTHING that claims one. What has changed is the thing that stops an untagged card reading
     * as empty. It used to be the argument the old version of this test recorded -- a bare tint
     * "reads as an empty box", answered first with a monogram (rejected: `HA` and `SE` decode to
     * nothing) and then with the evidence run on a plate (rejected with the plate). It is now the
     * card's lead figure, which every pack has and which no pack shares: `lib/packStat.ts`.
     *
     * That is why the second half of this test runs the ladder rather than reading the page. The
     * defect being guarded against is a card with no sector AND no figure, and only one of those
     * two is visible in the source text.
     */
    const cardStart = page.indexOf('function PackCard(');
    expect(cardStart, 'function PackCard must be locatable for this assertion').toBeGreaterThan(-1);
    const cardEnd = page.indexOf('\nfunction ', cardStart + 1);
    const card = page.slice(cardStart, cardEnd === -1 ? undefined : cardEnd);
    const cardCode = card
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
      .replace(/\/\/[^\n]*/g, '');

    // The sector reaches the card as a LABEL and never as a picture. `cat.icon` is what the
    // untagged packs all wore as one grey briefcase, and `UNLABELLED` is where that icon lives.
    expect(cardCode, 'the sector must not be drawn as a glyph').not.toMatch(
      /cat\.icon|category\.icon/,
    );
    expect(cardCode, 'the untagged fallback identity must not come back').not.toMatch(
      /UNLABELLED|monogram/i,
    );
    /*
     * Every sector rendering is behind a guard, so an untagged pack prints no empty chip.
     *
     * TWO SPELLINGS, BOTH ACCEPTED (2026-08-15). The `&&` form is the row's, which prints the
     * label inline in its meta row. The ternary form is what the two CARD variants now use, and
     * they use it because they no longer own their header: both pass
     * `label={cat.tagged ? cat.label : null}` to `PackCardHeader`, so the guard has to be an
     * expression rather than a statement. Counting only `&&` made this test fail on a change that
     * strengthened the very invariant it protects -- the header component renders nothing at all
     * for a falsy label, which is asserted directly below, so the guarantee is now made in ONE
     * place instead of being re-made correctly at three call sites.
     */
    const sectorPrints = cardCode.match(/cat\.label/g) ?? [];
    const sectorGuards = cardCode.match(/cat\.tagged (?:&&|\?)/g) ?? [];
    expect(sectorPrints.length, 'the card must print the sector as its own label').toBeGreaterThan(0);
    expect(
      sectorGuards.length,
      'every sector label must sit behind its own `cat.tagged` guard',
    ).toBe(sectorPrints.length);

    // The guarantee at its single source: the shared header draws nothing without a label, so a
    // card cannot print an empty band even if a future call site forgets to branch.
    const header = readSource('../../components/ui/PackCardHeader.tsx');
    expect(header, 'the shared header must gate its label').toMatch(/\{label &&/);

    // And the identity that does not depend on the sector at all: the pack's own figure, on
    // every variant. This is the part an untagged pack relies on.
    expect(
      (cardCode.match(/<PackFigure\b/g) ?? []).length,
      'every card variant must carry the pack figure',
    ).toBe(3);
  });

  it('an untagged pack still leads with a figure of its own', () => {
    const untagged: Pack = {
      id: 'cccc3333dddd4444',
      title: 'Bin store recycling signs for small flat blocks',
      oneLine: 'Signage kits for managing agents.',
      price: '£29.99',
      pricePence: 2999,
      paymentProvider: 'stripe',
      providerPriceId: 'price_test',
      sector: null,
      sourceCount: 39,
    };
    const stat = packLeadStat(untagged);
    expect(stat, 'a pack with no sector must still have something true to show').not.toBeNull();
    expect(stat!.figure.length, 'the figure must not be blank').toBeGreaterThan(0);
    expect(stat!.label.length, 'the figure must be named in words').toBeGreaterThan(0);
    // The figure owes nothing to the category, which is the whole reason it survives an absent
    // sector where every previous answer to this problem did not.
    const statSource = readSource('../packStat.ts').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(statSource, 'the figure must not be derived from the sector').not.toMatch(
      /sector|categor/i,
    );
  });

  it('UNLABELLED is still not in the rendered sector vocabulary', () => {
    expect(allCategories().map((c) => c.key)).not.toContain(UNLABELLED.key);
  });
});
