import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { readStylesheet } from './helpers/stylesheet';

/**
 * Three radii, two shadows (brand v3, 2026-08-06).
 *
 * THE DEFECT (counted 2026-08-05, across `src/ ** / *.tsx` excluding tests)
 *
 * Ten corner radii were in use: `rounded-full` 49, `-lg` 32, `-md` 17, bare `rounded` 11,
 * `-xl` 7, `-sm` 4, `-2xl` 3, `-[5px]` 2, `-r` 1, `-[10px]` 1. At card size, 4px and 5px and 6px
 * are the same corner, so the variation carried no hierarchy -- it just meant two cards side by
 * side had different corners.
 *
 * Fourteen distinct shadows, of which eleven were a 1-2px blur at 2-5% opacity sitting on an
 * element that already had a `border-border`. A shadow under a drawn border adds nothing but the
 * soft-product-UI look this palette exists to avoid.
 *
 * WHAT CHANGED FROM v2, AND WHY
 *
 * v2's rule was "two radii", one rectangle radius for everything. That put 8px on a 20px checkbox
 * and a 26px segmented pill, where the radius is 40% of the box height and the control reads as a
 * lozenge. Radius has to scale with the box, so `--radius-sm` (4px) is reinstated with a rule
 * stated by SIZE rather than by taste: 8px card-sized and up, 4px for controls under ~28px.
 *
 * WHAT CHANGED ON 2026-08-17, AND WHY THE COUNT WENT FROM THREE TO FIVE
 *
 * MASTER-BRIEF §4 declares "Radius 12px cards, 8px controls". That is a founder instruction and it
 * contradicts the size rule above, which had one 8px rectangle radius for everything card-sized and
 * up. The brief wins, but in a bounded way: TWO NEW TOKENS, `--radius-card` (12px) and
 * `--radius-ctl` (8px), adopted at the components that draw a card or a control.
 *
 * Retuning `--radius-md` to 12px was the smaller edit and it is the wrong one. That token sits on
 * 139 call sites of every size, so moving it would put a card's corner on a 20px checkbox and a
 * 26px segmented control -- the exact lozenge the paragraph above exists to prevent, arrived at
 * from the other direction.
 *
 * SO THE VOCABULARY IS STILL BOUNDED, AND THAT IS THE WHOLE POINT OF THIS FILE. Five names, each
 * with a stated job, is a vocabulary. Ten names picked from memory is what the defect count at the
 * top of this file was measuring. A sixth radius still fails here.
 *
 * v2's `shadow-hard` -- a 3px ink offset with no blur, canonised as "the brand device" -- is
 * deleted. On screen it is a sticker drop-shadow, and it is a large part of why the storefront was
 * rejected as unprofessional. The two legal shadows are now both real depth:
 *   shadow-1 -- a card lifting under the cursor, or the sticky header once it has scrolled;
 *   shadow-2 -- things that genuinely float: modal, drawer, command palette, mobile menu.
 * Anything else uses a border, or nothing.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (entry.endsWith('.tsx')) out.push(path);
  }
  return out;
}

// Comments stripped from the TSX too: these files explain the banned classes by name in prose
// (`Citation.tsx` documents the square chip it replaced), and a doc comment is not a rendered
// corner. Matching them made the suite fail on its own rationale.
const stripComments = (src: string) =>
  src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const TSX = walk(SRC).map((path) => ({
  path: path.slice(SRC.length),
  src: stripComments(readFileSync(path, 'utf8')),
}));
// Comments stripped: this file's siblings document the banned classes by name in prose.
// With local `@import`s inlined -- the radius and shadow tokens live in `styles/tokens.css` now.
// See `helpers/stylesheet.ts`.
const CSS = readStylesheet(join(SRC, 'styles', 'globals.css')).replace(/\/\*[\s\S]*?\*\//g, '');

/** Every radius utility, including the bare `rounded` and arbitrary `rounded-[5px]`. */
const RADIUS = /\brounded(?:-(?:[trbl]{1,2}-)?[a-z0-9[\]#%.]+)?\b/g;
const ALLOWED_RADII = new Set([
  'rounded-sm',    // 2px. Controls under ~28px: checkbox, chip, small badge.
  'rounded-md',    // 2px. The general rectangle, on 139 call sites.
  'rounded-card',  // 12px. MASTER-BRIEF §4. Card, StatCard, and anything that IS a card.
  'rounded-ctl',   // 8px.  MASTER-BRIEF §4. Button and Input -- a control you press or type in.
  'rounded-full',
  'rounded-none',
  'rounded-r-md',
]);

/** Every shadow utility, including arbitrary `shadow-[...]`. */
const SHADOW = /\bshadow-(?:\[[^\]]*\]|[a-z0-9-]+)/g;
const ALLOWED_SHADOWS = new Set(['shadow-1', 'shadow-2', 'shadow-none']);

describe('a bounded radius vocabulary, two shadows', () => {
  it('finds radii at all, so a rename cannot make this suite vacuous', () => {
    const n = TSX.reduce((a, f) => a + (f.src.match(RADIUS)?.length ?? 0), 0);
    expect(n, 'zero radius utilities means the pattern stopped matching').toBeGreaterThan(50);
  });

  it('uses no radius outside the two', () => {
    const offenders: string[] = [];
    for (const { path, src } of TSX) {
      src.split('\n').forEach((line, i) => {
        for (const m of line.match(RADIUS) ?? []) {
          if (!ALLOWED_RADII.has(m)) offenders.push(`${path}:${i + 1}  ${m}`);
        }
      });
    }
    expect(
      offenders,
      `Radius vocabulary is bounded to ${[...ALLOWED_RADII].join(', ')}. ` +
        `A card takes rounded-card, a control takes rounded-ctl, a small control takes ` +
        `rounded-sm. Offenders:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('uses no shadow outside the two', () => {
    const offenders: string[] = [];
    for (const { path, src } of TSX) {
      src.split('\n').forEach((line, i) => {
        for (const m of line.match(SHADOW) ?? []) {
          if (!ALLOWED_SHADOWS.has(m)) offenders.push(`${path}:${i + 1}  ${m}`);
        }
      });
    }
    expect(offenders, `only shadow-1 and shadow-2:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('the deleted tokens are gone from the stylesheet, not merely unused', () => {
    // Left declared, they are a standing invitation: the next component reaches for
    // `shadow-premium`, it resolves, and the consolidation is undone without a test firing.
    for (const dead of ['--radius-lg', '--shadow-hard', '--shadow-premium', '--shadow-vault',
                        '--shadow-tactile', '--elev-1', '--elev-2', '--elev-premium',
                        '--elev-tactile']) {
      expect(CSS, `${dead} must not be declared`).not.toContain(`${dead}:`);
    }
    expect(CSS).toContain('--shadow-1:');
    expect(CSS).toContain('--shadow-2:');
    expect(CSS).toContain('--radius-sm:');
    expect(CSS).toContain('--radius-md:');
    // Declared, and declared at the brief's sizes. A `rounded-card` whose token is missing from
    // @theme emits NO rule at all in Tailwind v4 -- the corner is simply square and nothing fails,
    // which is how a half-finished repaint ships looking merely plain. So pin the values.
    expect(CSS, 'MASTER-BRIEF §4: 12px cards').toMatch(/--radius-card:\s*12px/);
    expect(CSS, 'MASTER-BRIEF §4: 8px controls').toMatch(/--radius-ctl:\s*8px/);
  });
});
