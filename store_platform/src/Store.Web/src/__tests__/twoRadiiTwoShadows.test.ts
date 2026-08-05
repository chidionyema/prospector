import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Two radii, two shadows.
 *
 * THE DEFECT (counted 2026-08-05, across `src/ ** / *.tsx` excluding tests)
 *
 * Ten corner radii were in use: `rounded-full` 49, `-lg` 32, `-md` 17, bare `rounded` 11,
 * `-xl` 7, `-sm` 4, `-2xl` 3, `-[5px]` 2, `-r` 1, `-[10px]` 1. Four of those (4px, 5px, 6px,
 * 8px) are indistinguishable at arm's length, so the variation carried no hierarchy -- it just
 * meant two cards side by side had different corners.
 *
 * Fourteen distinct shadows, of which eleven were a 1-2px blur at 2-5% opacity sitting on an
 * element that already had a `border-border`. A shadow under a drawn border adds nothing but the
 * soft-product-UI look this palette exists to avoid.
 *
 * THE RULE
 *
 * Radii: `rounded-md` (6px) for every rectangle, `rounded-full` for pills, dots and avatars.
 * Shadows: `shadow-hard` (the 3px ink offset -- the brand device, on raised interactive things)
 * and `shadow-2` (the one soft shadow, only for surfaces that float OVER the page: modal,
 * drawer, command palette, mobile menu). Anything else uses a border, or nothing.
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

const TSX = walk(SRC).map((path) => ({ path: path.slice(SRC.length), src: readFileSync(path, 'utf8') }));
// Comments stripped: this file's siblings document the banned classes by name in prose.
const CSS = readFileSync(join(SRC, 'styles', 'globals.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

/** Every radius utility, including the bare `rounded` and arbitrary `rounded-[5px]`. */
const RADIUS = /\brounded(?:-(?:[trbl]{1,2}-)?[a-z0-9[\]#%.]+)?\b/g;
const ALLOWED_RADII = new Set(['rounded-md', 'rounded-full', 'rounded-none', 'rounded-r-md']);

/** Every shadow utility, including arbitrary `shadow-[...]`. */
const SHADOW = /\bshadow-(?:\[[^\]]*\]|[a-z0-9-]+)/g;
const ALLOWED_SHADOWS = new Set(['shadow-hard', 'shadow-2', 'shadow-none']);

describe('two radii, two shadows', () => {
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
    expect(offenders, `only rounded-md and rounded-full:\n${offenders.join('\n')}`).toEqual([]);
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
    expect(offenders, `only shadow-hard and shadow-2:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('the deleted tokens are gone from the stylesheet, not merely unused', () => {
    // Left declared, they are a standing invitation: the next component reaches for
    // `shadow-premium`, it resolves, and the consolidation is undone without a test firing.
    for (const dead of ['--radius-sm', '--radius-lg', '--shadow-1', '--shadow-premium',
                        '--shadow-vault', '--shadow-tactile', '--elev-1', '--elev-premium',
                        '--elev-tactile']) {
      expect(CSS, `${dead} must not be declared`).not.toContain(`${dead}:`);
    }
    expect(CSS).toContain('--shadow-hard:');
    expect(CSS).toContain('--radius-md:');
  });
});
