import { describe, it, expect } from 'vitest';
import { SITE_COPY } from '@/lib/siteCopy';
import report from '@/data/sample-report.json';

/*
  THE SAMPLE MAY NOT BE OVERSOLD BY THE LINKS THAT LEAD TO IT.

  MEASURED FAILURE, 2026-08-21. `/sample` stopped being a whole pack on 2026-08-15, when the
  founder settled it as a true excerpt: three sections in full, then a visible stop that names
  the eleven it withholds. `pages/sample.tsx` was rewritten that day, headline included -- "The
  opening of a real pack, in full."

  The three strings that link INTO it were not. `siteCopy.ts` still read "Read a full pack free
  -- no email needed" on the homepage hero, "Read a full pack free first" in the pack page's buy
  rail, and "Read a full pack free" everywhere else. So every route to the sample promised
  fourteen sections and delivered three, and the reader met that gap on the first click they
  make. Nothing failed. The page was honest, the links were not, and no gate compared them.

  WHY IT READS THE FIXTURE RATHER THAN PINNING A SENTENCE. A test that asserts the exact new
  wording locks the copy and says nothing about whether it is TRUE -- the same test would have
  passed all through the six days the claim was false, because it was the agreed wording then.
  What makes the claim false is the fixture: `sectionsShown` below `sectionsTotal`. So that is
  what decides. Widen the sample to all fourteen and the fixture flips, the rule lifts itself,
  and "a full pack free" is admissible again with no test to edit.
*/

/** Language that claims the reader gets the pack entire. */
const WHOLE_PACK = /\b(full|whole|complete|entire)\s+(pack|report)\b/i;

/** Every reader-facing string in the register that points a reader at /sample. */
const SAMPLE_LINK_KEYS = ['sampleLinkHero', 'sampleLinkPanel', 'sampleLink'] as const;

describe('the sample offer', () => {
  it('the fixture is internally consistent about how much it shows', () => {
    // The rule below is only as good as the numbers it reads, so grade them first. A fixture
    // whose counters disagree with its own arrays would silently switch the rule off.
    expect(report.excerpt.length).toBe(report.sectionsShown);
    expect(report.withheld.length).toBe(report.sectionsTotal - report.sectionsShown);
    expect(report.sectionsShown).toBeLessThan(report.sectionsTotal);
  });

  it('no link into /sample promises a whole pack while the fixture withholds sections', () => {
    const withholds = report.sectionsShown < report.sectionsTotal;
    if (!withholds) return; // The sample now shows everything; the claim would be true.

    const overclaims = SAMPLE_LINK_KEYS.filter((k) => WHOLE_PACK.test(SITE_COPY[k]));
    expect(
      overclaims,
      `/sample shows ${report.sectionsShown} of ${report.sectionsTotal} sections and names ` +
        `${report.withheld.length} it withholds, so these keys in siteCopy.ts claim more than ` +
        `the page delivers: ${overclaims.map((k) => `${k}=${JSON.stringify(SITE_COPY[k])}`).join(', ')}`,
    ).toEqual([]);
  });

  it('covers every register key that names the sample', () => {
    // An allow-list with a silent miss case is how a fourth link string would ship unguarded.
    // Anything in the register whose name starts with `sampleLink` must be in SAMPLE_LINK_KEYS.
    const named = Object.keys(SITE_COPY).filter((k) => k.startsWith('sampleLink'));
    expect(named.sort()).toEqual([...SAMPLE_LINK_KEYS].sort());
  });
});
