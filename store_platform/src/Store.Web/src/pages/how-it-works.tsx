import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { useCopyVariant } from '@/lib/useCopyVariant';
import killLog from '@/data/kill-log.json';

/** One entry from the kill log picked to illustrate a specific gate. */
interface KillExample {
  title: string;
  gate: string;
  gateLabel: string;
  reason: string;
}

const SIX_GATES: { gate: string; heading: string; exampleTitle: string }[] = [
  { gate: 'pain_reality', heading: 'Real pain', exampleTitle: 'NI-GapSweep' },
  { gate: 'value_durability', heading: 'Lasting value', exampleTitle: 'DecibelKit' },
  { gate: 'incumbency', heading: 'Room past the incumbents', exampleTitle: 'SaltCourt' },
  { gate: 'payer_solvency', heading: 'Payer can actually pay', exampleTitle: 'SplitCare' },
  { gate: 'route_to_market', heading: 'Route to the buyer', exampleTitle: 'AssessAid' },
  { gate: 'legality', heading: 'Legality', exampleTitle: 'GasSafe' },
];

function findExample(titleFragment: string): KillExample | undefined {
  return killLog.entries.find((e) => e.title.toLowerCase().includes(titleFragment.toLowerCase())) as
    | KillExample
    | undefined;
}

function truncateReason(reason: string, max: number): string {
  if (reason.length <= max) return reason;
  return reason.slice(0, max).replace(/\s+\S*$/, '') + '…';
}

export default function HowItWorks() {
  const { variant } = useCopyVariant();
  return (
    <MarketingLayout>
      <Seo
        title="How it works"
        description={variant.howItWorksSeoDescription}
      />

      <PageHero
        eyebrow={variant.howItWorksEyebrow}
        title={<span className="leading-tight tracking-tighter">{variant.howItWorksTitle}</span>}
        lead={variant.howItWorksLead}
      />

      {/* A. The six checks, as a stepped timeline */}
      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">{variant.sixChecksTitle}</span>}
      >
        <p className="mt-4 max-w-3xl text-base leading-relaxed text-text/75">
          {variant.sixChecksDescription}
        </p>

        <div className="mt-12 space-y-8">
          {SIX_GATES.map((gate, i) => {
            const example = findExample(gate.exampleTitle);
            return (
              <div
                key={gate.gate}
                className="relative flex gap-6"
              >
                {/* Step number + vertical line */}
                <div className="flex flex-col items-center flex-none">
                  <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-sm font-black text-white shadow-md">
                    {i + 1}
                  </span>
                  {i < SIX_GATES.length - 1 && (
                    <div className="mt-2 w-0.5 flex-1 bg-border/60" />
                  )}
                </div>

                {/* Card body */}
                <div className="flex-1 pb-6">
                  <h2 className="text-xl font-black text-text leading-tight">
                    {gate.heading}
                  </h2>
                  <p className="mt-1 font-mono text-xs font-bold uppercase tracking-widest text-primary">
                    <code className="bg-bg px-1.5 py-0.5 rounded text-[11px]">{gate.gate}</code>
                  </p>

                  {example && (
                    <div className="mt-5 rounded-xl border border-border bg-bg/40 p-5">
                      <p className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        {example.gateLabel}
                      </p>
                      <h3 className="mt-2 text-sm font-bold text-text leading-snug">
                        {example.title}
                      </h3>
                      <p className="mt-2 text-sm leading-relaxed text-text/75">
                        {truncateReason(example.reason, 160)}
                      </p>
                      <Link
                        href="/kill-log"
                        className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
                      >
                        See kill‑log <Icon name="arrowRight" size={12} />
                      </Link>
                    </div>
                  )}

                  {!example && (
                    <p className="mt-4 text-sm italic text-muted">
                      No example found in the kill log for this gate.
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      {/* B. The adversarial pass */}
      <Section
        bg="bg"
        width="6xl"
        title={<span className="font-black">The adversarial pass</span>}
      >
        <div className="max-w-3xl space-y-4">
          <p className="text-lg font-normal leading-relaxed text-text/80">
            After the six gates clear, a second agent attacks the surviving claim. It hunts for
            contradictions, weak citations, and gaps the first pass missed. The dossier survives
            only if every objection can be answered with the evidence already on file, no new
            research, no hand‑waving.
          </p>
          <p className="text-sm leading-relaxed text-muted">
            This is why silence in the evidence record means &ldquo;unverifiable,&rdquo; not
            &ldquo;false.&rdquo; The agent rules only on passages it actually fetched. If it
            cannot find the evidence, it cannot mount the kill, so the bar is high, and the
            surviving dossiers are the ones that cleared it honestly.
          </p>
        </div>
      </Section>

      {/* C. The graveyard */}
      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">Why most ideas die</span>}
      >
        <div className="max-w-3xl space-y-6">
          <p className="text-lg font-bold leading-relaxed text-text">
            Of 960 ideas researched, 103 survived.
          </p>
          <p className="text-base leading-relaxed text-text/80">
            The rejects are published in full, each with the gate that fired and the sourced
            argument that killed it. The filter is auditable, not a black box.
          </p>
          <Link
            href="/kill-log"
            className="inline-flex items-center gap-2 rounded-md bg-primary px-6 py-3 text-sm font-medium text-white transition-all hover:bg-primary-hover"
          >
            See the 960 we rejected{' '}
            <Icon name="arrowRight" size={15} />
          </Link>
        </div>
      </Section>

      {/* D. Honest limits, preserved verbatim */}
      <Section
        bg="bg"
        width="6xl"
        title={<span className="font-black">The honest limits</span>}
      >
        <div className="max-w-3xl space-y-6">
          <p className="text-lg font-normal leading-relaxed text-text/80">
            A pack is grounded research, not a guarantee. It&apos;s a high quality, evidence backed starting point. The work of finding, vetting, and sourcing the opportunity is done for you. Execution is still yours, and no analysis can promise a business outcome.
          </p>
        </div>
      </Section>

      <CtaBand
        title="See what made it through."
        lead=""
        primary={{ href: '/', label: 'Browse the packs' }}
      />
    </MarketingLayout>
  );
}
