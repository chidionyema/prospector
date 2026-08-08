import Link from 'next/link';
import report from '@/data/sample-report.json';
import { SourceChip } from '@/components/ui';
import { cx } from '@/components/ui/cx';

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
        <p className="text-caption text-subtle">The idea that went in</p>
        <h3 className="mt-2 text-h2 font-semibold leading-tight text-text">{report.title}</h3>
        <p className="mt-2 max-w-[62ch] text-meta leading-relaxed text-muted">{report.oneLiner}</p>
        {/* `slice(0, 10)` and not a formatter: `verifiedAt` is a full ISO timestamp with
            microseconds and a UTC offset, and printing the time of day implies a precision that
            means nothing about a research run. The ISO date is also the one date format that is
            unambiguous to a reader in any market, which matters on a page that sells UK and US
            research side by side. */}
        <p className="mt-3 font-mono text-caption text-subtle">
          {`${CHECKS.length} checks · ${report.sourceCount} sources · verified ${report.verifiedAt.slice(0, 10)}`}
        </p>
      </div>

      {/* THE RUN. An ordered list, because the order is the content: check eight only means what it
          means because seven checks had already held. */}
      <ol className="mt-6 list-none p-0">
        {CHECKS.map((check, i) => {
          const supported = check.verdict === 'supported';
          const last = i === CHECKS.length - 1;
          const domains = Array.from(new Set(check.sources.map(domainOf))).filter(Boolean);
          return (
            <li key={check.key} className={cx('relative flex gap-4', !last && 'pb-5')}>
              {/* The rail. `-mb-5` cancels the row's `pb-5` so the line runs through the padding
                  and meets the next node, rather than stopping at the content box and rendering
                  the run as eight detached segments. Same fix, same reason, as the timeline
                  below it. */}
              <div className="flex flex-none flex-col items-center">
                <span
                  className={cx(
                    'flex h-7 w-7 items-center justify-center rounded-sm font-mono text-caption',
                    // tokens.css:143 states it outright -- --kill on --kill-bg measures 4.41:1,
                    // under the AA floor -- and this pairing did exactly that. --kill-strong exists
                    // because of it and measures 5.91:1 on the same tint. The BORDER stays --kill:
                    // an edge is a UI boundary held to 3:1, not text.
                    supported
                      ? 'bg-survive text-bg'
                      : 'border border-kill bg-kill-bg text-kill-strong',
                  )}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                {!last && <div className="mt-1.5 -mb-5 w-px flex-1 bg-border" />}
              </div>

              <div className="min-w-0 flex-1 pb-1">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-body font-semibold leading-snug text-text">
                    {check.name}
                  </span>
                  {/* Never colour alone. The word states the verdict, the confidence states how
                      hard the engine was willing to state it, and both are set in mono because
                      both are readings rather than prose. A ruling at 0.41 that is printed as a
                      bare green tick is the overstatement this whole storefront exists against. */}
                  <span
                    className={cx(
                      'font-mono text-caption',
                      supported ? 'text-survive' : 'text-kill',
                    )}
                  >
                    {supported ? 'survived' : 'pushed back'}
                    <span className="text-subtle">{` · conf ${check.confidence.toFixed(2)}`}</span>
                  </span>
                </div>
                <p className="mt-1.5 max-w-[62ch] text-meta leading-relaxed text-muted">
                  {check.rationale}
                </p>
                {domains.length > 0 && (
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
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
                  </div>
                )}
              </div>
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
        <p className="font-mono text-caption text-text">
          <span className="text-survive">{SURVIVED} survived</span>
          <span className="text-subtle">{' · '}</span>
          <span className="text-kill">{PUSHED_BACK} pushed back</span>
          <span className="text-subtle">{` · ${report.sourceCount} sources cited`}</span>
        </p>
        <Link
          href="/sample"
          className="text-meta font-medium text-accent underline-offset-2 transition-colors hover:text-accent-hover hover:underline"
        >
          Read the whole evidence record
        </Link>
      </div>
    </div>
  );
}

export default CheckSequence;
