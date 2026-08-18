import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

import { LANDINGS } from '@/lib/seo/landings';

/**
 * `/ideas` BECAME `/collections`, AND THE OLD URLS STILL WORK (MASTER-BRIEF §7).
 *
 * A rename done with a find-and-replace is right up until it is not, and the two ways it goes
 * wrong are both silent. An internal link left on the old path 404s a reader who is already on the
 * site. A missing redirect throws away every ranking the sixteen landing pages have, plus every
 * link anyone has ever shared, and nothing in the build says a word about it.
 *
 * Both are cheap to state as a test, so they are stated here rather than remembered.
 *
 * ONE PATH SURVIVED THE SWEEP AND THIS IS WHY THE FILE SCAN IS BROAD. `checkLexicon.test.ts` built
 * its path as `join('pages', 'ideas', '[slug].tsx')` -- three separate segments, so the string
 * `/ideas` never appeared in it and the replace could not see it. It failed with an ENOENT rather
 * than an assertion, which was luck: the same shape in a `<Link href={...}>` built from parts would
 * have shipped.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const ROOT = fileURLToPath(new URL('../..', import.meta.url));

function walk(dir: string = SRC, out: { rel: string; src: string }[] = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'data') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(entry)) out.push({ rel: full.slice(SRC.length), src: readFileSync(full, 'utf8') });
  }
  return out;
}

/** Comments are argument. A note explaining the rename must not be read as a live path. */
const codeOnly = (src: string) =>
  src
    .split('\n')
    .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
    .join('\n');

const FILES = walk();
const NEXT_CONFIG = readFileSync(join(ROOT, 'next.config.ts'), 'utf8');

describe('the collections rename', () => {
  it('reads a non-trivial tree, so a broken walk cannot pass vacuously', () => {
    expect(FILES.length).toBeGreaterThan(100);
  });

  it('moved the pages', () => {
    expect(existsSync(join(SRC, 'pages', 'collections', 'index.tsx'))).toBe(true);
    expect(existsSync(join(SRC, 'pages', 'collections', '[slug].tsx'))).toBe(true);
    expect(existsSync(join(SRC, 'pages', 'ideas'))).toBe(false);
  });

  it('leaves no live link on the old path', () => {
    // Two files name the old path as data rather than as a destination: the mosaic test asserts
    // its ABSENCE, and this file reads the redirect rules that must keep it alive. A scan that
    // cannot exempt itself is a scan that has to be deleted the day it fires.
    const NAMES_IT_ON_PURPOSE = new Set([
      '__tests__/collectionMosaic.test.tsx',
      '__tests__/collectionsRename.test.ts',
    ]);
    const offenders = FILES.filter(({ rel }) => !NAMES_IT_ON_PURPOSE.has(rel))
      .filter(({ src }) => /['"`(]\/ideas\b/.test(codeOnly(src)))
      .map(({ rel }) => rel);
    expect(offenders, 'these still point at /ideas').toEqual([]);
  });

  it('redirects both old URLs permanently, slug rule first', () => {
    const slug = NEXT_CONFIG.indexOf('source: "/ideas/:slug"');
    const index = NEXT_CONFIG.indexOf('source: "/ideas"');
    expect(slug, 'the /ideas/:slug redirect is missing').toBeGreaterThan(-1);
    expect(index, 'the /ideas redirect is missing').toBeGreaterThan(-1);
    // Next.js takes the FIRST match. Reversed, `/ideas/evenings` would be tested against the
    // index rule before the slug rule and land on `/collections` with the slug thrown away.
    expect(slug, 'the slug rule must come first or every landing loses its slug').toBeLessThan(index);
    expect(NEXT_CONFIG.slice(slug, slug + 140)).toContain('permanent: true');
    expect(NEXT_CONFIG.slice(index, index + 120)).toContain('permanent: true');
  });

  it('calls the destination "Good for" in the chrome', () => {
    // THE LABEL MOVED AGAIN, AND THE WORD IS THE FOUNDER'S (2026-08-18, Plain English sweep).
    // "Collections" was on the founder's own ban list -- a word introduced by us that no reader
    // would say to a friend. The nav now reads "Good for" and the page heading reads
    // "Find one that suits how you work." The ROUTE is unchanged: renaming a path costs
    // redirects and a sitemap entry, and the label is what a reader sees.
    // The subject taxonomy keeps "Categories" on the individual landing pages, also the
    // founder's call, so this only fences the top-level chrome.
    const layout = readFileSync(join(SRC, 'components/marketing/MarketingLayout.tsx'), 'utf8');
    expect(codeOnly(layout)).not.toContain("label: 'Categories'");
    expect(codeOnly(layout)).not.toContain("label: 'Collections'");
    expect(layout).toContain("{ href: '/collections', label: 'Good for' }");
  });
});

describe('every collection has a written short name', () => {
  it('covers all sixteen', () => {
    expect(LANDINGS.length).toBe(16);
    for (const landing of LANDINGS) {
      expect(landing.shortName.trim().length, `${landing.slug} has no short name`).toBeGreaterThan(0);
    }
  });

  it('is short enough to be a tile label', () => {
    for (const landing of LANDINGS) {
      expect(landing.shortName.length, `${landing.shortName} is too long for a tile`).toBeLessThanOrEqual(24);
    }
  });

  it('is written, not cut out of the h1', () => {
    // §9 bans truncating text by character budget. A "short name" that is the first N characters
    // of the h1 is that ban worked around by hand, and it is what produced "Busin..." on the live
    // tiles. None of these may be a prefix of its own h1, and none may end in an ellipsis.
    for (const landing of LANDINGS) {
      expect(landing.shortName).not.toMatch(/[…]|\.\.\.$/);
      expect(
        landing.h1.startsWith(landing.shortName),
        `${landing.slug}: the short name is the front of the h1, which is a truncation`,
      ).toBe(false);
    }
  });

  it('is distinct, so two tiles never read the same', () => {
    const names = LANDINGS.map((l) => l.shortName.toLowerCase());
    expect(new Set(names).size).toBe(names.length);
  });
});

describe('the four signature graphics are on their pages', () => {
  const page = (rel: string) => readFileSync(join(SRC, 'pages', rel), 'utf8');

  it('collections renders the mosaic, above the detailed list', () => {
    const src = codeOnly(page('collections/index.tsx'));
    expect(src).toContain('<CollectionMosaic');
    expect(src).toContain('name: cat.shortName');
    expect(src.indexOf('<CollectionMosaic')).toBeLessThan(src.indexOf('<CategoryGraph'));
  });

  it('how-it-works renders the cascade from the shared distribution', () => {
    const src = codeOnly(page('how-it-works.tsx'));
    expect(src).toContain('<AttritionCascade distribution={distribution}');
    // Read once at build time from `buildKillIndex`, never a second table of counts typed here.
    expect(src).toContain('buildKillIndex().distribution');
    expect(src).not.toMatch(/byGate\s*:/);
  });

  it('pricing renders the matrix from the same ladder it draws', () => {
    const src = codeOnly(page('pricing.tsx'));
    expect(src).toContain('<IdenticalContentsMatrix');
    expect(src).toContain('documents={PACK_DOCUMENTS.length}');
    // The rungs come from the computed ladder, so the page cannot quote a price the shelf has not.
    expect(src).toMatch(/rungs=\{ladder\.map/);
  });
});

describe('the sample leads with what we could not settle', () => {
  const SAMPLE = readFileSync(join(SRC, 'pages', 'sample.tsx'), 'utf8');
  const CODE = codeOnly(SAMPLE);

  it('derives the unsettled checks from the pack, never types them', () => {
    expect(CODE).toContain("(c) => c.verdict !== 'supported'");
    expect(CODE).toContain('report.checks as SampleCheck[]');
  });

  it('puts the unsettled count ahead of the cleared count', () => {
    // §7: "lead with the check that failed". The cleared count is what every seller claims.
    expect(CODE.indexOf('PUSHED_BACK > 0')).toBeLessThan(CODE.indexOf('checks cleared'));
  });

  it('puts the block above the pack card', () => {
    expect(CODE.indexOf('id="unsettled"')).toBeGreaterThan(-1);
    expect(CODE.indexOf('id="unsettled"')).toBeLessThan(CODE.indexOf('>The pack<'));
  });

  it('flags it amber, because nothing died', () => {
    const block = CODE.slice(CODE.indexOf('id="unsettled"'), CODE.indexOf('>The pack<'));
    expect(block).toContain('border-warning');
    expect(block).toContain('bg-warning-bg');
    expect(block).not.toMatch(/-kill\b/);
  });

  it('has no email gate', () => {
    // §7 states this as an absolute, and it is the one thing that would undo the page: the sample
    // is the proof, and charging an address for it turns the proof into a lead magnet.
    expect(CODE).not.toMatch(/type="email"|name="email"/);
  });
});
