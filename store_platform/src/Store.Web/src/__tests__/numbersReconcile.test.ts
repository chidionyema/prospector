import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { RESEARCH_STATS, killsSummary, survivorsSummary } from '@/lib/stats';

const SRC = fileURLToPath(new URL('..', import.meta.url));

/**
 * THE NUMBERS ON THE PAGE MUST RECONCILE WITH EACH OTHER.
 *
 * The founder read the home page on 2026-08-13 and found this, on one scroll:
 *
 *   "50 packs to choose from"
 *   "1,444 ideas researched. 80 survived. That's a 6% pass rate."
 *   "80 survived the checks; 50 are packaged and listed so far.
 *    The other 1,364 are published, each with the evidence that killed it."
 *
 * Three independent arithmetic failures, on the storefront whose entire pitch is that it checks
 * its arithmetic, all measurable against `data/kill-log-totals.json` (killed 1,364, passed 80,
 * shown 400):
 *
 *   1. THE PARTITION DID NOT CLOSE. "The other" binds to the nearest number, 50, so the sentence
 *      claims 50 + 1,364 = 1,414 while the line above it prints 1,444. The 30 survivors that are
 *      not packaged yet simply vanished.
 *   2. "PUBLISHED" WAS ATTACHED TO THE WRONG COUNT. 400 kills are published, not 1,364, and
 *      /kill-log says exactly that one click away: "This page publishes 400 of those kills, not
 *      all 1,364." Two pages contradicted each other about one field of one JSON file.
 *   3. THE RATE DID NOT REPRODUCE. 6% of 1,444 is 87, and the previous clause says 80. The
 *      rounding was right; the printed number was still unreproducible from the two counts beside
 *      it. Ditto the kill side: 94% of 1,444 is 1,357, not 1,364.
 *
 * `lib/stats.ts` already existed to stop the site contradicting itself and already carried a
 * comment warning that `publishedKills` is "far smaller than `killed`, and the page must say so".
 * A shared source of numbers was not enough, because each page still wrote its own SENTENCE around
 * them. So the sentences are helpers now, and this file pins the properties they must hold.
 *
 * Everything here is a PROPERTY, never a digit: `tools/make_kill_log.py` regenerates the totals
 * and re-vetting moves them hard (survivors went 145 -> 83 in one regeneration on 2026-08-06).
 * A test that asserted "5.5%" would fail on the next batch and teach the next reader to update
 * the number rather than to keep the invariant.
 */
describe('the research counters reconcile with one another', () => {
  it('partitions every researched idea into survived or killed, with nothing left over', () => {
    const { researched, survived, killed } = RESEARCH_STATS;
    expect(survived + killed).toBe(researched);
  });

  it('never claims more kills are published than were killed', () => {
    expect(RESEARCH_STATS.publishedKills).toBeGreaterThan(0);
    expect(RESEARCH_STATS.publishedKills).toBeLessThanOrEqual(RESEARCH_STATS.killed);
  });

  it('never claims more packs are listed than survived', () => {
    // `survivorsSummary` degrades to the survivor count alone rather than printing a listed figure
    // that exceeds it, because `listed` comes from the live catalogue and the totals are a
    // build-time snapshot: the two can legitimately disagree for one deploy.
    const overstated = survivorsSummary(RESEARCH_STATS.survived + 5);
    expect(overstated).not.toContain('packaged and listed');
    expect(overstated).toContain('survived the checks');
  });
});

describe('a printed rate reproduces the count printed beside it', () => {
  // The reader's check is multiplication, so the test is multiplication. One idea of slack is what
  // a single decimal place buys; a whole percent was six ideas out on the pass rate (87 vs 80).
  const { researched, survived, killed, passRateLabel, rejectRateLabel } = RESEARCH_STATS;

  it('the pass rate lands within one idea of the survivor count', () => {
    const implied = (parseFloat(passRateLabel) / 100) * researched;
    expect(Math.abs(implied - survived)).toBeLessThanOrEqual(1);
  });

  it('the reject rate lands within one idea of the kill count', () => {
    const implied = (parseFloat(rejectRateLabel) / 100) * researched;
    expect(Math.abs(implied - killed)).toBeLessThanOrEqual(1);
  });

  it('keeps the two rates summing to 100 despite being derived separately', () => {
    expect(parseFloat(passRateLabel) + parseFloat(rejectRateLabel)).toBeCloseTo(100, 1);
  });

  it('no longer exposes a whole-percent rate for a page to reach for', () => {
    // The five call sites that printed the unreproducible figure were fixed by DELETING it. If a
    // future edit puts `passRate`/`rejectRate` back, the pages have a way to be wrong again.
    expect('passRate' in RESEARCH_STATS).toBe(false);
    expect('rejectRate' in RESEARCH_STATS).toBe(false);
  });
});

describe('the kill clause states its own antecedent', () => {
  const clause = killsSummary();
  const fmt = (n: number) => n.toLocaleString('en-GB');

  it('names the denominator instead of relying on "the other"', () => {
    // "The other 1,364" was the whole bug: English binds it to the nearest number, which was the
    // listed count, not the survivor count.
    expect(clause.toLowerCase()).not.toContain('the other');
    expect(clause).toContain(fmt(RESEARCH_STATS.researched));
  });

  it('puts only the published-kill count next to the word "published"', () => {
    expect(clause).toContain(`${fmt(RESEARCH_STATS.publishedKills)} of those kills are published`);
    const killedNextToPublished = new RegExp(
      `${fmt(RESEARCH_STATS.killed).replace(/,/g, ',')}[^.]{0,24}published`,
    );
    expect(clause).not.toMatch(killedNextToPublished);
  });

  it('reads as one sentence when the home page joins it to the survivor clause', () => {
    const paragraph = `${survivorsSummary(RESEARCH_STATS.survived - 1)}. ${clause}.`;
    // Every figure a reader can see in that paragraph, and the sum they will try.
    expect(paragraph).toContain(fmt(RESEARCH_STATS.survived));
    expect(paragraph).toContain(fmt(RESEARCH_STATS.killed));
    expect(paragraph).toContain(fmt(RESEARCH_STATS.publishedKills));
    expect(paragraph).toContain(fmt(RESEARCH_STATS.researched));
    expect(paragraph).not.toContain('..');
  });
});

describe('no page makes an absolute claim about kills being published', () => {
  // /how-it-works shipped "Every kill is published with the evidence that made it" while
  // /kill-log said "This page publishes 400 of those kills, not all 1,364". Only `lib/stats.ts`
  // may now form a sentence pairing kills with "published", and it uses `publishedKills`.
  const FORBIDDEN = /(every|all|each)[^.]{0,40}kills?[^.]{0,20}(is|are)\s+published/i;

  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return name === '__tests__' ? [] : walk(path);
      return /\.tsx?$/.test(name) ? [path] : [];
    });

  it('scans every page and component for the absolute form', () => {
    const offenders = walk(join(SRC, 'pages'))
      .concat(walk(join(SRC, 'components')))
      .filter((path) => FORBIDDEN.test(readFileSync(path, 'utf8')));
    expect(offenders).toEqual([]);
  });
});
