import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { Section, SectionBand } from '@/components/marketing/blocks';
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

type Source = { url: string; label: string };
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
        'inline-flex flex-none items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide',
        supported ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning',
      )}
    >
      <Icon name={supported ? 'check' : 'shield'} size={12} />
      {supported ? 'Survived' : 'Pushed back'}
    </span>
  );
}

export default function SamplePage() {
  const checks = report.checks as Check[];
  const scores = report.scores as Record<string, number>;
  const axes = Object.entries(AXIS_LABELS).filter(([k]) => k in scores);

  return (
    <MarketingLayout>
      <Seo title="Report #00, free. Read a whole stress-tested business report for zero pence." />

      {/* Hero */}
      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10 text-center">
        <p className="mb-4 font-mono text-xs font-bold uppercase tracking-[0.2em] text-muted">
          Report #00 · The free sample
        </p>
        <h1 className="mx-auto max-w-[20ch] text-balance text-4xl font-bold leading-[1.08] tracking-tight text-text md:text-5xl">
          Don&apos;t trust us? Read a whole report for zero pence.
        </h1>
        <p className="mx-auto mt-6 max-w-[60ch] text-base leading-relaxed text-text/75 md:text-lg">
          This is one full verification dossier, unredacted. Every check, every verdict, and every clickable
          source behind it. The same rigour sits behind every £49 pack in the catalogue. Read this one first,
          on the house.
        </p>
        <div className="mx-auto mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm font-semibold text-muted">
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
        <div className="rounded-2xl border border-border bg-white p-7 shadow-[0_1px_3px_rgba(0,0,0,0.04)] md:p-9">
          <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
            The opportunity
          </span>
          <h2 className="mt-2 text-2xl font-black leading-tight tracking-tight text-text md:text-3xl">
            {report.title}
          </h2>
          <p className="mt-4 max-w-[68ch] text-base leading-relaxed text-text/80">{report.oneLiner}</p>
          {report.whoPays && (
            <p className="mt-4 max-w-[68ch] text-sm leading-relaxed text-text/80">
              <span className="font-bold text-text">Who pays.</span> {report.whoPays}
            </p>
          )}
          {report.whyNow && (
            <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-text/80">
              <span className="font-bold text-text">Why now.</span> {report.whyNow}
            </p>
          )}
        </div>

        {/* Scorecard */}
        {axes.length > 0 && (
          <div className="mt-10">
            <h2 className="text-xl font-bold tracking-tight text-text">The stress test, scored</h2>
            <p className="mt-2 max-w-[60ch] text-sm text-muted">
              Scored on six axes out of five. The weak bars are shown too. That is the point.
            </p>
            <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
              {axes.map(([key, label]) => {
                const v = scores[key];
                const tone = v >= 4 ? 'bg-success' : v === 3 ? 'bg-primary' : 'bg-warning';
                return (
                  <div key={key} className="flex flex-col gap-1.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <dt className="text-sm font-semibold text-text">{label}</dt>
                      <dd className="font-mono text-xs font-bold text-muted">{v} / 5</dd>
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
          <h2 className="text-xl font-bold tracking-tight text-text">Every check, every source</h2>
          <p className="mt-2 max-w-[60ch] text-sm text-muted">
            Each gate is an attack the idea had to survive. Open any source and read it yourself. Nothing here
            is our opinion. It is what the pages actually said.
          </p>
          <ul className="mt-6 list-none space-y-4 p-0">
            {checks.map((ch, i) => (
              <li
                key={i}
                className="rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)] md:p-6"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h3 className="text-base font-bold text-text">{ch.name}</h3>
                  <VerdictBadge verdict={ch.verdict} />
                </div>
                <p className="mt-3 max-w-[68ch] text-sm leading-relaxed text-text/80">{ch.rationale}</p>
                {ch.sources.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2 border-t border-border/70 pt-4">
                    {ch.sources.map((s, j) => (
                      <a
                        key={j}
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        className="inline-flex max-w-full items-center gap-1.5 rounded-lg bg-bg px-2.5 py-1.5 text-xs font-semibold text-primary transition hover:bg-primary/10"
                      >
                        <Icon name="arrowRight" size={12} className="-rotate-45" />
                        <span className="truncate">{s.label}</span>
                      </a>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* The strongest argument against it */}
        {(report.premortem.strongestAlternative || report.adversarial.killCase) && (
          <div className="mt-10 rounded-2xl border border-warning/30 bg-warning/5 p-7 md:p-9">
            <div className="flex items-center gap-2">
              <Icon name="shield" size={16} className="text-warning" />
              <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-warning">
                The strongest case against it
              </span>
            </div>
            {report.adversarial.killCase && (
              <p className="mt-3 max-w-[68ch] text-sm leading-relaxed text-text/80">
                {report.adversarial.killCase}
              </p>
            )}
            {report.premortem.strongestAlternative && (
              <p className="mt-3 max-w-[68ch] text-sm leading-relaxed text-text/80">
                <span className="font-bold text-text">Your strongest free alternative.</span>{' '}
                {report.premortem.strongestAlternative}
              </p>
            )}
            <p className="mt-3 text-xs text-muted">
              We do not hide this. An idea that cannot survive its own best counter-argument never reaches the
              store.
            </p>
          </div>
        )}

        {/* CTA */}
        <div className="mt-12 rounded-2xl border border-border bg-white p-8 text-center shadow-[0_1px_3px_rgba(0,0,0,0.04)] md:p-10">
          <h2 className="mx-auto max-w-[24ch] text-balance text-2xl font-black tracking-tight text-text md:text-3xl">
            That was free. Every pack on the shelf is built like this.
          </h2>
          <p className="mx-auto mt-3 max-w-[56ch] text-base leading-relaxed text-text/75">
            The £49 pack adds the build spec, the go to market plan, and the operations playbook on top of the
            dossier you just read. One payment, yours to keep.
          </p>
          <Link
            href="/#catalog"
            className="mt-6 inline-flex items-center gap-2 rounded-full bg-primary px-6 py-3 text-sm font-bold text-white shadow-sm transition hover:opacity-90"
          >
            Browse the packs
            <Icon name="arrowRight" size={15} />
          </Link>
        </div>
      </Section>
    </MarketingLayout>
  );
}
