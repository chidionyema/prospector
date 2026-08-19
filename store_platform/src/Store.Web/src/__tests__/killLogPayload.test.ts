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
 * The corpus now lives behind the page's server data function and `/api/kill-log-detail`. These tests hold the
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
    // `killLog.server` is imported by the page, but only the SERVER data function may call it --
    // that is what lets Next strip it, and the JSON with it, from the client bundle.
    //
    // Either data function does that job, and on 2026-08-19 this page moved from `getStaticProps`
    // to `getServerSideProps` because it also prints the live shelf count, which a build-time
    // snapshot got wrong. The bundle rule is unchanged, so the check now names the mechanism it
    // actually cares about -- server-side, exactly once -- instead of one of the two spellings.
    const calls = page.split('\n').filter((l) => l.includes('buildKillIndex()'));
    expect(calls, 'buildKillIndex must be called once, inside the server data function').toHaveLength(1);
    const serverProps = /export const get(?:StaticProps|ServerSideProps)\b/.exec(page);
    expect(serverProps, 'the page has no server data function, so the corpus runs in the browser').not.toBeNull();
    const body = page.slice(serverProps!.index);
    expect(body).toContain('buildKillIndex()');
  });

  it('sends no prose in the props', () => {
    // The fields, named. A summary that regrows `reason` would still pass a size check on a small
    // fixture; this fails on the first row that carries one.
    //
    // `excerpt` is NOT on this list and that is a decision, taken 2026-08-17 under MASTER-BRIEF §7
    // ("the argument is the row"). The split was never about prose being expensive; it was about
    // 371 KB of prose nobody could see. The first 150 characters of each argument is 65 KB and it
    // is the only evidence on the page a reader gets without a tap. The full 198 KB of `reason`
    // stays behind the fetch, which is what the ban above holds in place.
    const banned = ['reason', 'oneLiner', 'citations'];
    const offenders = index.summaries
      .flatMap((s) => banned.filter((k) => k in s).map((k) => `${s.slug}.${k}`))
      .slice(0, 5);
    expect(offenders).toEqual([]);
  });

  it('keeps the props under the size they were measured at', () => {
    // A RATCHET on the payload that lands in the page's own HTML.
    //
    //   84,497 bytes  2026-08-16  slug, title, cause, date, source count
    //  149,153 bytes  2026-08-17  + `excerpt`, MASTER-BRIEF §7 -- 64,656 bytes, ~162 a row
    //  201,063 bytes  2026-08-18  excerpt is a whole first sentence, D3a -- ~289 a row
    //
    // Every number measured by this line. The ceiling has room for the log to grow but not for a
    // prose field to come back: `reason` alone is 198 KB and would blow straight through it.
    //
    // WHY IT MOVED. The excerpt was the first 150 characters of the argument with an ellipsis on
    // the end, and 364 of the 400 rows took that ellipsis. The founder reported it as a live
    // defect. A first sentence costs 52 KB more here (18 KB gzipped) and it is the only evidence
    // on the page a reader gets without a tap, so it is the field worth the bytes. `reason` is
    // still banned above and still 198 KB, so the ceiling below still catches the thing it was
    // built to catch.
    const bytes = JSON.stringify(index).length;
    expect(bytes, 'the kill-log page props grew -- did a prose field return?').toBeLessThan(220_000);
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
