import Link from 'next/link';
import report from '@/data/sample-report.json';
import killTotals from '@/data/kill-log-totals.json';
import { SourceChip, sourceHost } from '@/components/ui';
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

const SURVIVED = checks.filter((check) => check.verdict === 'supported').length;
const PUSHED_BACK = checks.length - SURVIVED;
const KILLED = (killTotals as { killed: number }).killed;

export function HeroEvidenceStrip({ className }: { className?: string }) {
  return (
    <div className={cx('max-w-[46rem]', className)}>
      <p className="text-caption text-subtle">
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
                  supported ? 'h-5 bg-survive' : 'h-5 border border-kill bg-kill-bg',
                )}
              />
            );
          })}
        </span>

        <p className="font-mono text-caption text-text">
          <span className="text-survive">{SURVIVED} survived</span>
          <span className="text-subtle">{' · '}</span>
          <span className="text-kill">{PUSHED_BACK} pushed back</span>
          <span className="text-subtle">{` · ${report.sourceCount} sources`}</span>
        </p>
      </div>

      {/* The domains are the part that cannot be faked, so they are the part that is clickable.
          `noopener` and the -45deg arrow copy `SourceChips` on `/sample` deliberately: this site
          has one way of drawing "a source you can open". */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {DOMAINS.slice(0, 4).map((domain) => (
          <SourceChip key={domain} url={HREF_FOR.get(domain) ?? ''} host={domain} variant="link" />
        ))}
        <Link
          href="/sample"
          className="font-medium text-caption text-accent underline-offset-2 transition-colors hover:text-accent-hover hover:underline"
        >
          See the whole thing
        </Link>
      </div>

      {/* The kill total lives HERE, attached to the record, because the two facts only mean
          something together: the checks have teeth (one just failed, above) and they have been
          applied at scale (this line). Split across the page they read as two boasts; adjacent
          they read as one method. The struck names drifting behind this column are the same
          records. */}
      <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-subtle">
        <span>
          {KILLED.toLocaleString('en-GB')} ideas were killed by these same checks.
        </span>
        <Link
          href="/kill-log"
          className="font-medium text-accent underline-offset-2 transition-colors hover:text-accent-hover hover:underline"
        >
          Read the kill log
        </Link>
      </p>
    </div>
  );
}

export default HeroEvidenceStrip;
