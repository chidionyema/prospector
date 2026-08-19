import Link from 'next/link';
import report from '@/data/sample-report.json';
import { SourceChip, VerdictChip, textLinkClass } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { ProofLine, sourcesLabel } from '@/components/ui/ProofLine';
import { plainEnglish } from '@/lib/plainEnglish';

/*
  ONE REAL IDEA, RUN THROUGH THE CHECKS IN ORDER.

  WHAT PROBLEM THIS SOLVES. /how-it-works described the filter in the abstract and then, separately,
  showed six unrelated ideas that each died on a different gate. Both halves are true and neither
  shows the thing the page is actually about: what happens to ONE idea when it is put through the
  checks in order. A reader could finish the page knowing that six gates exist and still not know
  what a run looks like end to end.

  So this is a single subject entering at the top, each check firing on it in sequence, and the
  verdict landing on each -- including the one that lands badly. The kill examples keep their place
  below: this shows a run that survives, the kills show the same machinery when it does not,
  and the two together are the argument.

  WHERE THE DATA COMES FROM. `sample-report.json`, the same file `/sample` renders in full and the
  home page's `HeroEvidenceStrip` compresses to a glyph run. Every name, verdict, confidence, rationale
  and source URL below is read from it. Nothing on this page is written by hand, so this sequence
  cannot drift from the evidence record it claims to be showing, and the reader can open /sample and find
  the identical eight rows.

  WHY IT IS NOT A THIRD COPY OF THAT RECORD. `HeroEvidenceStrip` renders the SHAPE (how many, how they
  came out, which domains). `EvidenceRecordPanel` on the home page renders the ANSWERS. This renders the
  SEQUENCE: the order, the confidence the engine put on each ruling, and the fact that check eight
  reversed the run. Order and confidence appear nowhere else on the site.
*/

type Source = { url: string; domain?: string; label: string };
type Check = {
  name: string;
  key: string;
  verdict: string;
  confidence: number;
  rationale: string;
  sources: Source[];
};

const CHECKS = report.checks as Check[];
const SURVIVED = CHECKS.filter((check) => check.verdict === 'supported').length;
const PUSHED_BACK = CHECKS.length - SURVIVED;

/* The report's sources carry a `domain` field already; the URL parse is the fallback for older
   fixtures that do not. Falling back to the raw URL would print a 90-character string into a
   caption slot, so an unparseable URL contributes no chip at all. */
function domainOf(source: Source): string {
  if (source.domain) return source.domain.replace(/^www\./, '');
  try {
    return new URL(source.url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

export function CheckSequence({ className }: { className?: string }) {
  return (
    <div className={cx('max-w-3xl', className)}>
      {/* THE IDEA ENTERING. Named, in its own words, before anything is done to it -- a run
          with an anonymous subject is a diagram, not a demonstration. */}
      <div className="rounded-md bg-surface2 p-5 sm:p-6">
        <p className="mono">The idea that went in</p>
        <h3 className="mt-2 leading-tight sub">{report.title}</h3>
        <p className="mt-2 max-w-[62ch] lede">{report.oneLiner}</p>
        {/* ONE PROOF-LINE FORMAT SITEWIDE (MASTER-BRIEF section 10). This line, the catalogue
            row, the summary strip below and the /sample hero all said the same thing in four
            different wordings, because each was written where it stood. The wording is now one
            decision in `ProofLine`; this call site only chooses which parts it has room for. */}
        <ProofLine
          checks={CHECKS.length}
          sources={report.sourceCount}
          verifiedAt={report.verifiedAt}
          className="mt-3"
        />
      </div>

      {/* THE RUN. An ordered list, because the order is the content: check eight only means what it
          means because seven checks had already held. */}
      <ol className="mt-6 list-none p-0">
        {CHECKS.map((check, i) => {
          const supported = check.verdict === 'supported';
          const domains = Array.from(new Set(check.sources.map(domainOf))).filter(Boolean);
          return (
            /* THE DRAWING'S `.checkrow` (`mockups/how-it-works.html:89-95`): a three-column grid,
               32px for the numeral, the reading in the middle, the verdict tag hard right, one
               hairline under each row. This was a vertical rail with a 28px node per check and a
               1px line threading them. The rail is not in any mockup, and it was the reason the
               numeral, the heading, the rationale and the source line were all set by hand here
               instead of by the class the drawing styles. */
            <li key={check.key} className="checkrow">
              {/* `num` too: the drawing sets the numeral in the mono face
                  (`mockups/pack-detail.html:499`, `<span class="i num">05</span>`), and `.num` is
                  what carries that. Without it the column was set in the body face. */}
              <span className="i num">{String(i + 1).padStart(2, '0')}</span>

              <div className="min-w-0">
                <h3>{check.name}</h3>
                <p>{plainEnglish(check.rationale)}</p>
                {domains.length > 0 && (
                  /* `.checkrow .srcs` is the mono source line under the reading. A `<p>`, as the
                     drawing writes it (`mockups/pack-detail.html:499`): it is one line of prose
                     with links in it, sitting under the paragraph above it, not a container. */
                  <p className="srcs flex flex-wrap items-center gap-x-3 gap-y-1">
                    {domains.map((domain) => {
                      const source = check.sources.find((s) => domainOf(s) === domain);
                      return (
                        <SourceChip
                          key={domain}
                          url={source?.url ?? ''}
                          host={domain}
                          variant="link"
                        />
                      );
                    })}
                  </p>
                )}
              </div>

              {/* NEVER COLOUR ALONE: the tag carries the verdict WORD and a glyph, not a tick.
                  `· conf 0.87` used to follow the name here, and SITE_SPEC 2 P0 rule 4 forbids a
                  raw float on a marketing page. It stays omitted. */}
              <VerdictChip kind={supported ? 'survived' : 'pushed-back'} />
            </li>
          );
        })}
      </ol>

      {/* WHERE IT CAME OUT. The counts, and nothing about what the counts entitle the idea to.
          This evidence record is published as the free sample; whether an idea with one refuted check gets
          listed is a decision `kill_filter.py` makes on which gate fired and whether the ruling was
          a cited kill, and this component cannot see either. Stating the outcome would be asserting
          a rule the page has not shown. The counts are the fact; /sample is the whole record. */}
      <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-md bg-surface2 p-5">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-caption text-text">
          <VerdictChip kind="survived" label={`${SURVIVED} survived`} />
          {/* Amber, not red. Red is reserved for a KILL (MASTER-BRIEF §2), and a pushed-back check
              is not a kill: the check found nothing decisive either way, the idea continued, and
              the doubt stays on the record. Red told a reader the idea had failed something it had
              not. The chip is what makes that a property of the component rather than of this
              line. */}
          <VerdictChip kind="pushed-back" label={`${PUSHED_BACK} pushed back`} />
          <span className="text-subtle">{`${sourcesLabel(report.sourceCount)} cited`}</span>
        </p>
        <Link
          href="/sample"
          className={textLinkClass('text-meta font-medium')}
        >
          Read the whole evidence record
        </Link>
      </div>
    </div>
  );
}

export default CheckSequence;
