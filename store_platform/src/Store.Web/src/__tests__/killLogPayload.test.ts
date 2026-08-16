import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { buildKillDetails, buildKillIndex } from '@/lib/killLog.server';
import { plainEnglish } from '@/lib/plainEnglish';

const SRC = fileURLToPath(new URL('..', import.meta.url));

/**
 * WHAT A READER DOWNLOADS TO READ FOUR HUNDRED TITLES.
 *
 * Measured on the live site 2026-08-16, before this split:
 *
 *   /kill-log   HTML 32,563 gz   JS 301,456 gz   of which ONE chunk 151,754 gz / 459,488 raw
 *
 * That chunk was `src/data/kill-log.json`, bundled by a static import at the top of the page. It
 * is 456 KB, 371 KB of which is the one-liner, the reason and the citation list -- three fields
 * that render only inside a row the reader has expanded. So every visitor downloaded and parsed
 * four hundred arguments in order to look at four hundred titles, and a static JSON import cannot
 * be tree-shaken away.
 *
 * The corpus now lives behind `getStaticProps` and `/api/kill-log-detail`. These tests hold the
 * split in place, because it is the kind of fix a single convenient import silently undoes.
 */
describe('the kill log ships the table, not the corpus', () => {
  const index = buildKillIndex();

  it('does not statically import the corpus into the page', () => {
    // The direct form of the defect. This assertion FAILS on the code as it stood yesterday: line
    // 8 of the page read `import killLog from '@/data/kill-log.json';`. Anything importing that
    // file from a module a component can reach puts all 456 KB back in the browser.
    const page = readFileSync(`${SRC}/pages/kill-log.tsx`, 'utf8');
    // An IMPORT of it, not a mention of it: the page carries a comment naming the file to say it
    // must never be imported again, and a guard that cannot tell the rule from its violation would
    // make writing the rule down an offence.
    const imports = page
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => /^import\b|\brequire\(|\bimport\(/.test(l) && l.includes('kill-log.json'));
    expect(imports, 'the corpus is back in the client bundle').toEqual([]);
    // `killLog.server` is imported by the page, but only `getStaticProps` may call it -- that is
    // what lets Next strip it, and the JSON with it, from the client bundle.
    const calls = page.split('\n').filter((l) => l.includes('buildKillIndex()'));
    expect(calls, 'buildKillIndex must be called once, inside getStaticProps').toHaveLength(1);
    const body = page.slice(page.indexOf('export const getStaticProps'));
    expect(body).toContain('buildKillIndex()');
  });

  it('sends no prose in the props', () => {
    // The fields, named. A summary that regrows `reason` would still pass a size check on a small
    // fixture; this fails on the first row that carries one.
    const banned = ['reason', 'oneLiner', 'citations'];
    const offenders = index.summaries
      .flatMap((s) => banned.filter((k) => k in s).map((k) => `${s.slug}.${k}`))
      .slice(0, 5);
    expect(offenders).toEqual([]);
  });

  it('keeps the props under the size they were measured at', () => {
    // A RATCHET on the payload that lands in the page's own HTML. 84,497 bytes measured
    // 2026-08-16 for 400 rows of slug, title, cause, date and source count; the ceiling has room
    // for the log to grow but not for a prose field to come back (`reason` alone is 198 KB).
    const bytes = JSON.stringify(index).length;
    expect(bytes, 'the kill-log page props grew -- did a prose field return?').toBeLessThan(120_000);
  });

  it('gives every row an argument to open, under the same slug', () => {
    // The slug is computed twice, in two exported functions, and a disagreement would show up as
    // rows that open onto nothing -- silently, and only for the titles that collide.
    const details = buildKillDetails();
    const missing = index.summaries.filter((s) => !details[s.slug]).map((s) => s.slug);
    expect(missing).toEqual([]);
    expect(Object.keys(details)).toHaveLength(index.summaries.length);
  });

  it('translates the argument once, at build time', () => {
    // `plainEnglish` used to run on every render and inside the search filter, over both prose
    // fields of all 400 rows, for every keystroke. It now runs here. Idempotence is the check that
    // the output really is translated: a string that changes when translated again was not.
    const details = buildKillDetails();
    const untranslated = Object.entries(details)
      .filter(([, d]) => plainEnglish(d.reason) !== d.reason || plainEnglish(d.oneLiner) !== d.oneLiner)
      .map(([slug]) => slug)
      .slice(0, 3);
    expect(untranslated).toEqual([]);
  });

  it('still counts the sources it no longer sends', () => {
    // The count is a table column and a sort key, so it stays in the props while the list does
    // not. Cross-checked against the detail payload rather than restated from the same source.
    const details = buildKillDetails();
    const wrong = index.summaries
      .filter((s) => s.sources !== details[s.slug].citations.length)
      .map((s) => s.slug);
    expect(wrong).toEqual([]);
    expect(index.withSource).toBe(index.summaries.filter((s) => s.sources > 0).length);
  });
});
