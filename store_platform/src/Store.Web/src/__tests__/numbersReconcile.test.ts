import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { RESEARCH_STATS, killsSummary } from '@/lib/stats';

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
  it('derives the researched total rather than trusting a typed-in number', () => {
    // `researched` is killed + cleared, computed in lib/stats.ts. Two pages once printed 1,168 and
    // 1,313 for the same quantity, both reading the same JSON.
    expect(RESEARCH_STATS.researched).toBeGreaterThan(RESEARCH_STATS.killed);
  });

  it('never claims more kills are published than were killed', () => {
    expect(RESEARCH_STATS.publishedKills).toBeGreaterThan(0);
    expect(RESEARCH_STATS.publishedKills).toBeLessThanOrEqual(RESEARCH_STATS.killed);
  });
});

describe('the survivor count is not available to any page', () => {
  /*
   * FOUNDER DIRECTIVE, 2026-08-13, verbatim: "saying 80 when only 50 are listed should never
   * happen regardless of the reasons why survivors are unlisted."
   *
   * 80 ideas cleared the gates and 50 are on the shelf. The site printed the 80 in five places,
   * including the footer of every page, and then spent three revisions writing copy to explain
   * why it was bigger than the shelf: first stating the gap ("50 are packaged and listed so far"),
   * then reconciling the whole partition in the marketing paragraph. Both were us volunteering our
   * packaging backlog to defend a number we chose to print.
   *
   * The fix is that the number is not exported. tsc is the real enforcement -- `RESEARCH_STATS`
   * has no `survived` -- and these assertions exist so that a future edit adding it back trips a
   * test that explains WHY rather than only a type error. `passRateLabel` goes with it because a
   * pass rate is the survivor count in another form: 5.5% of 1,444 is the 80 we do not claim.
   */
  it('exports no survivor count and no pass rate', () => {
    expect('survived' in RESEARCH_STATS).toBe(false);
    expect('passRateLabel' in RESEARCH_STATS).toBe(false);
    expect('passRate' in RESEARCH_STATS).toBe(false);
    expect('rejectRate' in RESEARCH_STATS).toBe(false);
  });

  it('exports no helper that formats a survivor sentence', () => {
    // `survivorsSummary()` was deleted, not reworded. While it existed, every page that wanted a
    // survivor figure had a sanctioned way to print one.
    const stats = RESEARCH_STATS as Record<string, unknown>;
    expect(Object.keys(stats).sort()).toEqual(
      ['killed', 'publishedKills', 'rejectRateLabel', 'researched', 'survivorBoundLabel'],
    );
  });

  /**
   * `survivorBoundLabel` was added on 2026-08-16 so the pack page could LEAD with the survivor
   * reading. It used to lead with the kill rate and then spend its next sentence turning it round,
   * and a reader scanning a rail of figures gets the headline, not the correction.
   *
   * It is the only figure on the survivor side of the partition the 2026-08-13 directive allows,
   * and the only reason it is allowed is that it is a BOUND and not a rate. So the bound-ness is
   * asserted rather than assumed: a decimal place, or a rounding that landed near the true figure,
   * would make this the deleted `passRateLabel` under a new name, and multiplying it back would
   * hand the reader the 80 we do not claim.
   */
  it('the survivor bound is a BOUND, so it cannot be read back as the survivor count', () => {
    const { researched, killed, survivorBoundLabel } = RESEARCH_STATS;
    const trueSurvivors = researched - killed;
    const impliedByBound = (parseInt(survivorBoundLabel, 10) / 100) * researched;

    // A whole number in 100. A decimal place is what makes a rate reproducible, which is the
    // virtue of `rejectRateLabel` two describes down and the defect here.
    expect(survivorBoundLabel).toMatch(/^\d+ in 100$/);
    // Rounded UP, so "this many or fewer get through" is true rather than nearly true.
    expect(impliedByBound).toBeGreaterThan(trueSurvivors);
    // And far enough above that the reader who multiplies does not land on the count. The sister
    // test below asserts the exact opposite of `rejectRateLabel` -- within one idea -- for the
    // opposite reason. The two together are the whole policy.
    expect(impliedByBound - trueSurvivors).toBeGreaterThan(1);
  });
});

describe('a printed rate reproduces the count printed beside it', () => {
  // The reader's check is multiplication, so the test is multiplication. One idea of slack is what
  // a single decimal place buys; a whole percent was seven ideas out on the kill count.
  const { researched, killed, rejectRateLabel } = RESEARCH_STATS;

  it('the kill rate lands within one idea of the kill count', () => {
    const implied = (parseFloat(rejectRateLabel) / 100) * researched;
    expect(Math.abs(implied - killed)).toBeLessThanOrEqual(1);
  });

  it('carries a decimal place, because a whole percent does not multiply back', () => {
    expect(rejectRateLabel).toMatch(/^\d+\.\d%$/);
  });
});

describe('the kill clause carries no counts at all', () => {
  const clause = killsSummary();

  // "The other 1,364 are published" was two bugs in four words: "the other" binds to the nearest
  // number, which was the listed count, and 400 kills are published, not 1,364. The first repair
  // wrote every denominator into the clause. The founder cut it: a clause with no digits in it
  // cannot mis-bind, cannot contradict the totals printed above it, and cannot go stale.
  it('prints no digits, so it cannot disagree with any number on the page', () => {
    expect(clause).not.toMatch(/\d/);
  });

  it('does not reach for a pronoun whose antecedent is off in another clause', () => {
    expect(clause.toLowerCase()).not.toContain('the other');
    expect(clause.toLowerCase()).not.toContain('the remaining');
  });

  it('does not use kill or die words', () => {
    expect(clause.toLowerCase()).not.toMatch(/\b(kill|kills|die|died|survive|survived)\b/);
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

  it('finds no page reaching for a survivor figure by any of its old names', () => {
    // Belt and braces over tsc: a page could re-derive the figure straight from the JSON
    // (`killTotals.passed`) and typecheck perfectly, which is how the survivor count got printed
    // in seven places before `lib/stats.ts` existed at all.
    const REACHING = /RESEARCH_STATS\.survived|survivorsSummary|passRateLabel|killTotals\b[^;]*\.passed|\.passed\.toLocaleString/;
    const offenders = walk(join(SRC, 'pages'))
      .concat(walk(join(SRC, 'components')))
      .filter((path) => REACHING.test(readFileSync(path, 'utf8')));
    expect(offenders).toEqual([]);
  });
});

describe('a label may not make the claim the sentence guard refuses', () => {
  /*
   * THE 2026-08-13 DEFECT SURVIVED IN CAPTIONS FOR SEVENTEEN DAYS.
   *
   * The guard above scans for the absolute SENTENCE ("every kill is published") and for a page
   * reaching past `lib/stats.ts` for a survivor figure. It reads whole files as prose, so it
   * never noticed that three pages carried the same false claim as a two-word LABEL sitting
   * directly over the killed count:
   *
   *   about.tsx      <dt><span>Killed, published</span></dt>      over 1,364
   *   pricing.tsx    Ideas killed, published                      over 1,364
   *   index.tsx      <p className="lbl">Researched, not listed</p> over 1,364
   *
   * 400 kills are published, not 1,364, and /kill-log says exactly that one click away. The home
   * page label was wrong twice over: it read as inventory waiting to be listed rather than as
   * ideas rejected on evidence, and researched-but-unlisted is 1,444 - 77 = 1,367 anyway.
   *
   * A label is where a claim hides, because it is short enough to look like a name. So labels are
   * scanned as claims from here on. The general rule is the second `it`: the word "published"
   * belongs in prose on /kill-log, which states its own scope, and never in a caption.
   */
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return name === '__tests__' ? [] : walk(path);
      return /\.tsx?$/.test(name) ? [path] : [];
    });

  const pageFiles = () => walk(join(SRC, 'pages')).concat(walk(join(SRC, 'components')));

  // JSX comments are where this file's own history is written, and every one of them quotes the
  // wrong label it replaced. Strip them, or the guard fails on the record of its own fix.
  const stripComments = (source: string) => source.replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, ' ');

  // A label is read with the value it labels, never on its own: "Published here" over
  // `publishedKills` is the one place on the site that claim is true, and it is the sentence on
  // /kill-log turned into a figure. So each label carries the source that follows it, and the
  // rule below asks what the number underneath actually is.
  const labelsIn = (source: string): { words: string; value: string }[] => {
    const text = stripComments(source);
    const found: { words: string; value: string }[] = [];
    for (const re of [/<dt\b[^>]*>([\s\S]{0,400}?)<\/dt>/g, /className="lbl"[^>]*>([\s\S]{0,300}?)<\/p>/g]) {
      for (const match of text.matchAll(re)) {
        const words = match[1].replace(/<[^>]*>/g, ' ').replace(/\{[^}]*\}/g, ' ').replace(/\s+/g, ' ').trim();
        const end = (match.index ?? 0) + match[0].length;
        if (words) found.push({ words, value: text.slice(end, end + 240) });
      }
    }
    return found;
  };

  it('finds no caption pairing a kill count with the word published', () => {
    const offenders = pageFiles().filter((path) =>
      /kills?(ed)?,\s*published/i.test(stripComments(readFileSync(path, 'utf8'))),
    );
    expect(offenders).toEqual([]);
  });

  it('lets a label say published only when the figure under it is the published count', () => {
    const offenders = pageFiles().flatMap((path) =>
      labelsIn(readFileSync(path, 'utf8'))
        .filter((label) => /publish/i.test(label.words) && !/publishedKills/.test(label.value))
        .map((label) => `${path}: ${label.words}`),
    );
    expect(offenders).toEqual([]);
  });

  it('flags the caption this repair removed, so the rule is proved on the bug it was written for', () => {
    // A guard that has never fired on its own defect is a guess. This is `about.tsx:163` as it
    // shipped from 2026-08-13 to 2026-08-30, verbatim.
    const shipped =
      "<dt><span>Killed, published</span></dt>\n<dd><b className=\"num\">{totals.killed.toLocaleString('en-GB')}</b></dd>";
    expect(/kills?(ed)?,\s*published/i.test(shipped)).toBe(true);
    const flagged = labelsIn(shipped)
      .filter((label) => /publish/i.test(label.words) && !/publishedKills/.test(label.value))
      .map((label) => label.words);
    expect(flagged).toEqual(['Killed, published']);
  });

  it('reads the labels it is scanning, so a broken matcher cannot pass by finding nothing', () => {
    // Without this the two rules above go green the day the JSX shape changes and `labelsIn`
    // starts returning an empty list -- the silent-green class this estate keeps paying for.
    const all = pageFiles().flatMap((path) => labelsIn(readFileSync(path, 'utf8')));
    expect(all.length).toBeGreaterThan(15);
    expect(all.some((label) => /^Killed$/i.test(label.words))).toBe(true);
    // The one true "published" caption on the site. If this stops being found, the rule above is
    // passing because it can no longer see labels at all.
    expect(all.some((label) => /publish/i.test(label.words))).toBe(true);
  });
});
