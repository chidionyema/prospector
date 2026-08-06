import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses, Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { Section, SectionBand } from '@/components/marketing/blocks';
import { WaitlistCallout } from '@/components/waitlist/WaitlistCallout';
import { freshnessLabel } from '@/lib/api/client';
import report from '@/data/sample-report.json';

// The six scored axes, in the order we show them, with human labels.
const AXIS_LABELS: Record<string, string> = {
  pain_acuity: 'Pain acuity',
  money_provability: 'Money provability',
  defensibility: 'Defensibility',
  distribution: 'Distribution',
  build_feasibility: 'Build feasibility',
  automatability: 'Automatable vs hands on',
};

type Source = { url: string; domain: string; label: string };
type Check = {
  name: string;
  key: string;
  verdict: string;
  confidence: number;
  rationale: string;
  sources: Source[];
};

function VerdictBadge({ verdict }: { verdict: string }) {
  const supported = verdict === 'supported';
  return (
    <span
      className={cx(
        'inline-flex flex-none items-center gap-1.5 rounded-full px-2.5 py-1 text-caption font-medium',
        supported ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning',
      )}
    >
      <Icon name={supported ? 'check' : 'shield'} size={12} />
      {supported ? 'Survived' : 'Pushed back'}
    </span>
  );
}

/**
 * The row of openable sources under a block of the report.
 *
 * Extracted so the premortem panel gets the same affordance as the eight checks. It did not have
 * one: its citations were the raw 16-hex passage hashes the engine embeds in prose, printed
 * literally, e.g. "(e646bf90d84a4530, a95e55366ce78462)" (desktop-sample-full.png, 2026-08-06).
 * `tools/make_sample_report.py` now resolves those to the real URLs and drops any it cannot
 * resolve, so this renders three openable pages where the page used to print a hex blob.
 *
 * The domain leads, and is never omitted. This chip used to show the page title alone, taken from
 * the first line of the fetched text, and 2 of the 11 chips on this page came out as "INTRODUCTORY
 * NOTES" and "- Sample Report": a citation the reader cannot attribute to anyone, on the one page
 * whose whole argument is "open it and check who said this". `/kill-log` already led with the
 * domain (`kill-log.tsx:198`), so the site described a source two different ways depending which
 * evidence page you were on. Mono for the domain, because that is the checkable datum, and the
 * title stays sans as supporting prose.
 */
function SourceChips({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  return (
    <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
      {sources.map((s) => (
        <a
          key={s.url}
          href={s.url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-muted transition-colors hover:border-border-strong hover:text-text"
        >
          <Icon name="arrowRight" size={12} className="-rotate-45 shrink-0" />
          <span className="font-mono font-medium text-text">{s.domain}</span>
          {s.label && <span className="truncate">{s.label}</span>}
        </a>
      ))}
    </div>
  );
}

export default function SamplePage() {
  const checks = report.checks as Check[];
  const scores = report.scores as Record<string, number>;
  const axes = Object.entries(AXIS_LABELS).filter(([k]) => k in scores);

  return (
    <MarketingLayout>
      <Seo title="Report #00, free. Read a whole stress-tested business report for zero pence." />

      {/* Hero. Left-aligned, like every other marketing hero on the site.
          This one was hand-rolled with `text-center` and a stack of `mx-auto`s, so /sample -- the
          page whose entire job is "here is the evidence, judge us" -- was the only page in the set
          that centred its headline and a 60ch paragraph (desktop-sample-fold.png vs
          desktop-about-fold.png, 2026-08-06). `PageHero` had already recorded why that is wrong
          (blocks.tsx:61): a centred ragged-both-edges paragraph starts every line at a different x.
          The rule existed; this page just was not using the component that carried it. */}
      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10">
        <p className="mb-4 text-caption font-medium text-muted">
          Report #00 · The free sample
        </p>
        <h1 className="max-w-[20ch] text-balance text-h1 font-semibold text-text md:text-display">
          Don&apos;t trust us? Read a whole report for zero pence.
        </h1>
        <p className="mt-6 max-w-[60ch] text-body leading-relaxed text-muted">
          This is one full verification dossier, unredacted. Every check, every verdict, and every clickable
          source behind it. The same rigour sits behind every pack in the catalogue. Read this one first,
          on the house.
        </p>
        <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-2 text-meta font-semibold text-muted">
          <span className="inline-flex items-center gap-2">
            <Icon name="check" size={14} className="text-success" />
            {report.supported} of {report.total} checks survived
          </span>
          <span className="inline-flex items-center gap-2">
            <Icon name="verified" size={14} className="text-success" />
            {report.sourceCount} cited sources
          </span>
          {freshnessLabel(report.verifiedAt) && (
            <span className="inline-flex items-center gap-2">
              <Icon name="scheduled" size={14} />
              {freshnessLabel(report.verifiedAt)}
            </span>
          )}
        </div>
      </SectionBand>

      <Section bg="bg" width="6xl" className="!pt-6 !pb-24">
        {/* The idea */}
        <div className="rounded-md border border-border bg-surface p-7 md:p-9">
     <span className="text-caption font-medium text-muted">
            The opportunity
          </span>
          <h2 className="mt-2 text-h2 font-semibold text-text md:text-h1">
            {report.title}
          </h2>
          <p className="mt-4 max-w-[68ch] text-body leading-relaxed text-muted">{report.oneLiner}</p>
          {report.whoPays && (
            <p className="mt-4 max-w-[68ch] text-meta leading-relaxed text-muted">
              <span className="font-semibold text-text">Who pays.</span> {report.whoPays}
            </p>
          )}
          {report.whyNow && (
            <p className="mt-2 max-w-[68ch] text-meta leading-relaxed text-muted">
              <span className="font-semibold text-text">Why now.</span> {report.whyNow}
            </p>
          )}
        </div>

        {/* Scorecard */}
        {axes.length > 0 && (
          <div className="mt-10">
            <h2 className="text-h2 font-semibold text-text">The stress test, scored</h2>
            <p className="mt-2 max-w-[60ch] text-meta text-muted">
              Scored on six axes out of five. The weak bars are shown too. That is the point.
            </p>
            <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
              {axes.map(([key, label]) => {
                const v = scores[key];
                const tone = v >= 4 ? 'bg-success' : v === 3 ? 'bg-text/40' : 'bg-warning';
                return (
                  <div key={key} className="flex flex-col gap-1.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <dt className="text-meta font-semibold text-text">{label}</dt>
                      <dd className="font-mono text-caption font-medium text-muted">{v} / 5</dd>
                    </div>
                    <div className="flex gap-1" aria-hidden>
                      {Array.from({ length: 5 }).map((_, i) => (
                        <span
                          key={i}
                          className={cx('h-1.5 flex-1 rounded-full', i < v ? tone : 'bg-border')}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </dl>
          </div>
        )}

        {/* The checks */}
        <div className="mt-10">
          <h2 className="text-h2 font-semibold text-text">Every check, every source</h2>
          <p className="mt-2 max-w-[60ch] text-meta text-muted">
            Each gate is an attack the idea had to survive. Open any source and read it yourself. Nothing here
            is our opinion. It is what the pages actually said.
          </p>
          <ul className="mt-6 list-none space-y-4 p-0">
            {checks.map((ch, i) => (
              <li
                key={i}
                className="rounded-md border border-border bg-surface p-5 md:p-6"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h3 className="text-body font-semibold text-text">{ch.name}</h3>
                  <VerdictBadge verdict={ch.verdict} />
                </div>
                <p className="mt-3 max-w-[68ch] text-meta leading-relaxed text-muted">{ch.rationale}</p>
                <SourceChips sources={ch.sources} />
              </li>
            ))}
          </ul>
        </div>

        {/* The strongest argument against it */}
        {(report.premortem.strongestAlternative || report.adversarial.killCase) && (
          <div className="mt-10 rounded-md border border-warning/30 bg-warning/5 p-7 md:p-9">
            <div className="flex items-center gap-2">
              <Icon name="shield" size={16} className="text-warning" />
              {/* Sans. This is a section heading in English, not a verdict tag: it names the
                  block, it is not a value the reader would transcribe or compare. */}
              <span className="text-caption font-medium text-warning">
                The strongest case against it
              </span>
            </div>
            {report.adversarial.killCase && (
              <p className="mt-3 max-w-[68ch] text-meta leading-relaxed text-muted">
                {report.adversarial.killCase}
              </p>
            )}
            {report.premortem.strongestAlternative && (
              <p className="mt-3 max-w-[68ch] text-meta leading-relaxed text-muted">
                <span className="font-semibold text-text">Your strongest free alternative.</span>{' '}
                {report.premortem.strongestAlternative}
              </p>
            )}
            <p className="mt-3 text-caption text-muted">
              We do not hide this. An idea that cannot survive its own best counter-argument never reaches the
              store.
            </p>
            <SourceChips sources={report.premortem.sources} />
          </div>
        )}

        {/* CTA */}
        <div className="mt-12 rounded-md border border-border bg-surface p-8 text-center md:p-10">
          <h2 className="mx-auto max-w-[24ch] text-balance text-h2 font-semibold text-text md:text-h1">
            That was free. Every pack on the shelf is built like this.
          </h2>
          <p className="mx-auto mt-3 max-w-[56ch] text-body leading-relaxed text-muted">
            A pack adds the build spec, the go to market plan, and the operations playbook on top of the
            dossier you just read. One payment, yours to keep.
          </p>
          <Link
            href="/#catalog"
            className={buttonClasses({ size: 'lg', className: 'mt-6' })}
          >
            Browse the packs
            <Icon name="arrowRight" size={15} />
          </Link>
        </div>

        {/* Second position, under the buy CTA: a reader who wants a pack should buy one, and the
            address is only the fallback when nothing on the shelf fits them yet. */}
        <WaitlistCallout />
      </Section>
    </MarketingLayout>
  );
}
