import { createHash } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { DEFAULT_OG_IMAGE_PATH } from '@/lib/seo/ogImage';

/**
 * Guards the static brand assets in `public/`.
 *
 * THE INCIDENT. On 2026-08-14 the founder reported seeing "remnants of the introduction exchange"
 * when sharing a link to the site. They were not remnants: `public/og.png` was the complete
 * link-preview card of a different product -- "The Intro Exchange / Warm introductions to the
 * people you can't reach cold." -- and `favicon.ico` ("E") plus `apple-touch-icon.png`,
 * `icon-192.png` and `icon-512.png` ("IX" on navy) were that product's icon set. All five were
 * committed in `5f95ca7` on 16 Jun and never touched again, while `public/icon.svg` alone was
 * updated to the Mumchimp strata mark on 13 Aug. `Seo.tsx` nominates the default card on every
 * route except pack pages, so for two months every share of the home page, /sample, /kill-log and
 * the rest previewed as another company.
 *
 * WHAT MADE IT SURVIVE, and therefore what these tests check. Nothing tied the rasters to the
 * mark. The suite was green, the site looked right in a browser tab (the SVG favicon was correct),
 * and the only surface that was wrong is one no developer looks at -- a scraper's cache. Each
 * assertion below is one of the links that was missing, not a restatement of the fix.
 */

const WEB = path.resolve(__dirname, '../..');
const readPublic = (f: string) => readFileSync(path.join(WEB, 'public', f));

const LOCK = JSON.parse(
  readFileSync(path.join(WEB, 'scripts', 'brand-assets.lock.json'), 'utf8'),
) as { source: string; sha256: string; generates: string[]; regenerate: string };

describe('brand assets', () => {
  /**
   * The link the incident was missing. Redrawing the mark without re-running the generator is
   * exactly what happened between 13 Aug (icon.svg updated) and 14 Aug (rasters still IX), and
   * before this test there was nothing anywhere that could notice.
   */
  it('rasters are generated from the current icon.svg', () => {
    const current = createHash('sha256').update(readPublic('icon.svg')).digest('hex');
    expect(
      current,
      `public/icon.svg has changed since the rasters were generated. Run: ${LOCK.regenerate}`,
    ).toBe(LOCK.sha256);
  });

  it('every asset the generator claims to produce exists and is non-trivial', () => {
    for (const rel of LOCK.generates) {
      const size = statSync(path.join(WEB, rel)).size;
      expect(size, `${rel} is empty or truncated`).toBeGreaterThan(512);
    }
  });

  /**
   * `icon.svg` used to render in every browser while NOT being valid XML: its explanatory comment
   * contained a literal `--`, and a double hyphen inside `<!-- -->` is malformed. librsvg (which
   * sharp uses) rejects the whole document on it, which is why the generator strips comments
   * before rasterising. The 2026-08-14 redraw removed the offending hyphens, so the last assertion
   * below keeps them out rather than tolerating them. Pinned because the failure is invisible from
   * the product -- the favicon looks perfect while the file is unrasterisable -- and the fix lives
   * in a script nobody reads until it breaks.
   */
  it('icon.svg carries the shape the rasters are cut from', () => {
    const svg = readPublic('icon.svg').toString('utf8');
    const body = svg.replace(/<!--[\s\S]*?-->/g, '');

    // Three solid slabs, no container (founder decision 2026-08-14, option D of six).
    //
    // REDRAWN 2026-08-18 to the shape in the build bundle. The slabs used to be a 100x100 funnel
    // running from (3,6)-(97,6) to (37,94)-(63,94), which finished on a flat bar. All twelve
    // mockups (docs/design/mumchimp-build-bundle/mockups/*.html, header and footer of each) draw a
    // 26-wide funnel that tapers to a POINT. Same idea, different drawing, and the drawing is the
    // only thing a logo has to get right. The top and bottom slabs are asserted literally because
    // they carry the full taper between them.
    expect(body.match(/<path\b/g) ?? [], 'the mark is three slab paths').toHaveLength(3);
    expect(body).toContain('M1 2h24l-4.1 5H5.1L1 2Z');
    expect(body).toContain('M10.7 17h4.6L13 22.5 10.7 17Z');

    // The tile must not come back, in either of its two parts. `<rect>` was the band primitive,
    // and a white fill was how the bands were knocked out of the solid ground -- which is also
    // what made the old favicon wrong on a dark tab strip, since those knockouts were white INK
    // sitting on transparency, not holes.
    expect(body.match(/<rect\b/g) ?? [], 'the knocked-out tile must not return').toHaveLength(0);
    expect(body, 'nothing in the mark is white').not.toMatch(/fill="#(?:fff|ffffff)"/i);

    // A double hyphen inside any comment makes the whole document unrasterisable.
    for (const comment of svg.match(/<!--[\s\S]*?-->/g) ?? []) {
      expect(comment.slice(4, -3), 'no "--" inside an XML comment').not.toContain('--');
    }
  });

  /**
   * Replacing the bytes at an unchanged URL does not reach a scraper that has already cached the
   * old card, and Slack/X/LinkedIn/Facebook all cache on a timescale of weeks. Without a version
   * token the fix above is invisible on precisely the links already shared.
   */
  it('the default card path is cache-busted', () => {
    expect(DEFAULT_OG_IMAGE_PATH).toMatch(/^\/og\.png\?v=\d{4}-\d{2}-\d{2}$/);
  });

  /**
   * `_document.tsx` and `Seo.tsx` are separate <Head> trees, so next/head's `key` dedupe cannot
   * see across them: both declarations shipped, and _document's pointed at an SVG, which iOS does
   * not support for a home-screen tile at all.
   */
  it('declares exactly one apple-touch-icon, pointing at a PNG', () => {
    const sources = ['src/pages/_document.tsx', 'src/components/Seo.tsx']
      .map((f) => readFileSync(path.join(WEB, f), 'utf8'))
      .join('\n')
      // Comments in these files discuss the removed declaration by name; the test is about what
      // renders, so strip them rather than have prose fail the assertion.
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '');
    const declarations = sources.match(/<link[^>]*rel="apple-touch-icon"[^>]*>/g) ?? [];
    expect(declarations).toHaveLength(1);
    expect(declarations[0]).toMatch(/href="[^"]+\.png"/);
  });
});
