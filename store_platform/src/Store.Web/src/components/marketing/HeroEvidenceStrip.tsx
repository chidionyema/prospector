import Link from 'next/link';
import report from '@/data/sample-report.json';
import { SourceChip, sourceHost, textLinkClass } from '@/components/ui';
import { cx } from '@/components/ui/cx';

/*
  The evidence record, in the hero, at one glance.

  WHY IT MOVED. The full `EvidenceRecordPanel` sits roughly 80% down this page. It is the single most
  persuasive object the shop owns -- eight named checks, real verdicts, one of them a REFUTAL, and
  a live link to the source behind each -- and a stranger had to scroll past the entire shelf to
  meet it. The proposition of this business is "the checking already happened, and you can audit
  it", so the first screen should be able to say that with evidence rather than with an adjective.

  WHY THIS IS NOT A SECOND COPY OF `EvidenceRecordPanel`. Two renderings of the same eight rows on one
  page is the "same paragraph four times" defect this pass exists to remove. So the strip and the
  panel are deliberately different OBJECTS with different jobs: this is the SHAPE of a record
  (how many checks, how they came out, where the evidence came from) at a glance, and it links to
  the panel below, which is the CONTENT (what each check asked, and its answer). Nothing here
  restates a sentence from down there.

  Every number and every domain is read from `sample-report.json`, the same JSON `/sample` renders
  in full. Nothing is typed in by hand, so the strip cannot drift from the report it describes.
*/

type Source = { url: string; label: string };
type Check = { name: string; verdict: string; sources: Source[] };

const checks = report.checks as Check[];


/*
  The distinct source domains, in first-appearance order. Distinct, because the persuasive fact is
  the SPREAD of independent places the evidence came from; printing the same domain three times
  because three checks happened to use it argues the opposite of what it means to argue.
*/
const DOMAINS = Array.from(
  new Set(checks.flatMap((check) => check.sources.map((source) => sourceHost(source.url)))),
).filter(Boolean);

// The first source URL for a given domain, so each chip is a real anchor rather than a printed
// string. This page's headline promise is that every claim links to its source; a domain rendered
// as a <span> inside the hero would break that promise in the one place it is being made.
const HREF_FOR = new Map<string, string>();
checks.forEach((check) => {
  check.sources.forEach((source) => {
    const domain = sourceHost(source.url);
    if (domain && !HREF_FOR.has(domain)) HREF_FOR.set(domain, source.url);
  });
});

/*
  The chips the strip actually draws, and the word that counts them.

  `mockups/index.html:304` labels this row "Four of the 29 sources behind the free sample pack",
  and "Four" there is a typed-in word beside a hand-written list. Here both halves are read from
  the report: the label cannot say four while the row draws three, which is the failure mode of
  every hand-written count on this page that has already been removed. The word list stops at the
  chip limit because that is the largest number this row can ever show.
*/
const CHIP_LIMIT = 4;
const SHOWN_DOMAINS = DOMAINS.slice(0, CHIP_LIMIT);
const COUNT_WORDS = ['No', 'One', 'Two', 'Three', 'Four'] as const;
const SHOWN_WORD = COUNT_WORDS[SHOWN_DOMAINS.length] ?? String(SHOWN_DOMAINS.length);

const SURVIVED = checks.filter((check) => check.verdict === 'supported').length;
const PUSHED_BACK = checks.length - SURVIVED;

export function HeroEvidenceStrip({ className }: { className?: string }) {
  return (
    /* NO MEASURE OF ITS OWN. This used to cap itself at 46rem, which was right while it lived
       inside the hero's left column. It is now the drawing's own `.srcstrip` section
       (`mockups/index.html:304`), a full-width row under the hero, and the caller sets the
       measure. */
    <div className={cx(className)}>
      <p className="mono">
        Every pack carries this. Here is the one in the free sample.
      </p>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* The eight verdicts as eight marks, in the order the checks ran. This is the whole
            record compressed to a single glyph run: a reader takes in "eight checks, one of them
            went badly" without reading a word, which is more than the sentence beside it can do in
            the same 20mm of screen. It is not colour-only -- the shapes differ (a full bar for a
            survival, a hollow one for a push-back) and the count is spelled out immediately
            after. */}
        <span className="flex items-end gap-1" aria-hidden>
          {checks.map((check, i) => {
            const supported = check.verdict === 'supported';
            return (
              <span
                key={i}
                className={cx(
                  'block w-2 rounded-sm',
                  /* AMBER, NOT RED (2026-08-14 colour audit, finding 3). A check that was
                     pushed back on a pack that SURVIVED is not a kill, and tokens.css states
                     the rule this restores: "Red and green are reserved for exactly one meaning
                     on this site: killed and survived." Spending red on a non-fatal check
                     spends the one signal the kill-log depends on. It also ends the strip
                     contradicting itself -- `/sample:43` already draws this identical state as
                     `--warning-strong` on `--warning-bg` (6.84:1), so the page carried two
                     colour families for one state. `--warning-strong` also fixes the contrast
                     miss underneath: `--kill` on `--kill-bg` measures 4.41:1. */
                  supported
                    ? 'h-5 bg-survive'
                    : 'h-5 border border-pushed-back-strong bg-pushed-back-bg',
                )}
              />
            );
          })}
        </span>

        <p className="font-mono text-caption text-text">
          <span className="text-survive">{SURVIVED} survived</span>
          <span className="text-subtle">{' · '}</span>
          {/* Matches the ticks above, and for the same reason. See the note on their class.
              The token is `--pushed-back-strong` now, not `--warning-strong`: same value, but the
              name says the verdict rather than a generic UI state, so the next person to read
              this line cannot mistake it for a caution message. */}
          <span className="text-pushed-back-strong">{PUSHED_BACK} pushed back</span>
          <span className="text-subtle">{` · ${report.sourceCount} sources`}</span>
        </p>
      </div>

      {/* THE ROW'S OWN LABEL, from the drawing (`mockups/index.html:304`). The strip had none: the
          chips sat under the verdict bar with nothing saying they were a SAMPLE of a longer list,
          so four domains read as the whole evidence base rather than as four of twenty-nine. The
          mockup's em dash is a comma-and-full-stop here, per the founder's standing note on
          dashes in copy. */}
      <p className="mt-4 text-caption text-subtle">
        {`${SHOWN_WORD} of the ${report.sourceCount} sources behind the free sample pack. Every claim in every pack links back to one.`}
      </p>

      {/* The domains are the part that cannot be faked, so they are the part that is clickable.
          `noopener` and the -45deg arrow copy `SourceChips` on `/sample` deliberately: this site
          has one way of drawing "a source you can open". */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {SHOWN_DOMAINS.map((domain) => (
          <SourceChip key={domain} url={HREF_FOR.get(domain) ?? ''} host={domain} variant="pill" />
        ))}
        <Link
          href="/sample"
          className={textLinkClass('font-medium text-caption')}
        >
          See the whole thing
        </Link>
      </div>

      {/* THE KILL TOTAL AND ITS "Read the kill log" LINK USED TO CLOSE THIS COMPONENT, and the
          argument for putting them here was right: the checks have teeth (one just failed, above)
          and they have been applied at scale, and those two facts only mean something adjacent.

          What made it wrong was arithmetic, not reasoning. Measured on the rendered page at
          1440x900, "1,364" appeared at y=735 here and again at y~1180 in the proof strip, each
          under an identically-worded link to the same page: one number, twice, on one screen, on a
          site whose entire pitch is that it keeps track of its numbers.

          The bridge itself is not lost, it MOVED ONTO THE PICTURE. `KillGrid` renders in the
          hero column beside this component and its caption reads "Every idea we have ever
          researched, one square each" over 1,444 squares -- the same sentence, doing the same
          work, said once, beside the population it is about instead of 445px above a restatement
          of it. The
          prose statement of both totals stays in the proof strip, which is the only one of the
          three that a phone ever sees. */}
    </div>
  );
}

export default HeroEvidenceStrip;
