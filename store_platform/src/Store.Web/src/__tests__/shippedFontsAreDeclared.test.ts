import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * PUBLIC/FONTS AND THE @FONT-FACE BLOCKS MUST NAME THE SAME FILES, IN BOTH DIRECTIONS.
 *
 * A typeface change moves every letter on every page, so it gets made once and then nobody looks
 * at the directory again. Measured on 2026-08-30, after Inter and IBM Plex Mono replaced Switzer
 * and Commit Mono: `public/fonts` still held `Switzer-Variable.woff2` (43,220 bytes) and
 * `CommitMono-400.woff2` (48,128 bytes), 91,348 bytes shipped in every deploy and referenced by
 * no `@font-face` rule anywhere in the repo. Nothing failed. Nothing could: no test read the
 * directory.
 *
 * The other direction is the one a reader notices. A `src:` pointing at a file that is not there
 * does not error -- the browser silently falls back to the system face, so the page renders in
 * the wrong typeface and every check stays green.
 */
const WEB = path.resolve(__dirname, '../..');
const FONT_DIR = path.join(WEB, 'public', 'fonts');
const TOKENS = readFileSync(path.join(WEB, 'src', 'styles', 'tokens.css'), 'utf8');

/** Every `/fonts/...` file the stylesheet asks the browser to fetch. */
const declared = new Set(
  [...TOKENS.matchAll(/url\(['"]\/fonts\/([^'"]+)['"]\)/g)].map((m) => m[1]),
);

const onDisk = new Set(readdirSync(FONT_DIR).filter((f) => f.endsWith('.woff2')));

describe('shipped fonts', () => {
  it('declares an @font-face for every file it ships', () => {
    expect([...onDisk].filter((f) => !declared.has(f)).sort()).toEqual([]);
  });

  it('ships a file for every @font-face it declares', () => {
    expect([...declared].filter((f) => !onDisk.has(f)).sort()).toEqual([]);
  });

  /**
   * A guard that reads an empty set passes for the wrong reason. Three faces ship: the Inter
   * variable file, and the 400 and 500 cuts of IBM Plex Mono.
   */
  it('is reading real declarations, not an empty set', () => {
    expect(declared.size).toBe(3);
  });
});
