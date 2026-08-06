import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, buttonClasses, textLinkClass } from '@/components/ui';
import { BRAND } from '@/lib/config';
import killTotals from '@/data/kill-log-totals.json';

/**
 * L2 - The about page.
 *
 * The audit (§6) said the store was "a single voice" with no face. The
 * about page is the human face of the brand. It explains the engine, the
 * six checks, the kill log, and the "source-or-die" voice. The story is
 * the moat; the page is the moat rendered as a person.
 */
export default function AboutPage() {
  const totals = killTotals as { killed: number; passed: number };
  return (
    <MarketingLayout>
      <Seo
        title={`About ${BRAND.name} - the engine behind the packs`}
        description={`How ${BRAND.name} works: an engine that tries to kill every business idea on six checks. ${totals.killed} killed, ${totals.passed} survived.`}
      />

      <section className="mx-auto max-w-3xl px-6 py-16 md:py-24">
    <p className="mb-3 text-caption font-medium text-muted">
          About
        </p>
        <h1 className="text-h1 font-semibold text-text md:text-display">
          We try to kill every idea.
        </h1>
        <p className="mt-4 max-w-[60ch] text-body leading-relaxed text-muted md:text-h2">
          {BRAND.name} is an engine that runs business ideas through six
          brutal checks. The ones that die on the first front where cited
          evidence is found against them are not listed. The ones that
          survive all six are the {BRAND.name} packs. Right now the kill
          count is{' '}
          <span className="font-semibold text-text">{totals.killed.toLocaleString('en-GB')}</span>
          {' '}and the survivors are{' '}
          <span className="font-semibold text-text">{totals.passed}</span>.
        </p>

        <div className="mt-12">
          <h2 className="text-h2 font-semibold text-text md:text-h1">
            The six checks
          </h2>
          <p className="mt-2 max-w-[60ch] text-body text-muted">
            Every idea is attacked on the same six fronts. An idea dies on
            the first front where cited evidence is found against it. A
            listed pack is one where none of the six produced that evidence.
          </p>
          {/* Two columns from `sm` up. Six numbered cards holding three words and a short question
              each, stacked full width, ran the length of the viewport with most of every card
              empty (desktop-about-fold.png, 2026-08-06). Numbered order still reads correctly:
              CSS grid fills row-major, so 1-2 / 3-4 / 5-6. */}
          <ol className="mt-6 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
            {[
              { name: 'Real demand', desc: 'Is the pain real, or are we imagining it?' },
              { name: 'Lasting value', desc: 'Does the value decay, or is it durable?' },
              { name: 'Room past the incumbents', desc: 'Have the big players already won?' },
              { name: 'Someone will pay', desc: 'Is the buyer actually solvent?' },
              { name: 'A route to the buyer', desc: 'Can the product reach the market?' },
              { name: 'No legal landmine', desc: 'Is there a regulatory path?' },
            ].map((check, i) => (
              <li key={check.name} className="flex items-start gap-3 rounded-md border border-border bg-surface p-4">
        <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-border bg-bg text-caption font-medium text-muted">
                  {i + 1}
                </span>
                <div>
                  <p className="text-meta font-semibold text-text">{check.name}</p>
                  <p className="mt-0.5 text-meta leading-relaxed text-muted">
                    {check.desc}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="mt-12">
          <h2 className="text-h2 font-semibold text-text md:text-h1">
            The kill log
          </h2>
          <p className="mt-2 max-w-[60ch] text-body text-muted">
            Most of the ideas the engine runs are killed. We do not hide
            that. Every kill is in the{' '}
            <Link href="/kill-log" className={textLinkClass('font-medium')}>
              kill log
            </Link>
            , with the cited argument that killed it. The log is the receipt
            behind the catalogue; the catalogue is the survivors of the log.
          </p>
          <p className="mt-4 max-w-[60ch] text-body text-muted">
            The voice is <span className="font-semibold text-text">source-or-die</span>.
            Sourced, not sold. Refutational, not promotional. If a claim
            has no source, it is not in a pack. If an idea cannot survive
            the filter, it is not on the shelf.
          </p>
        </div>

        <div className="mt-12">
          <h2 className="text-h2 font-semibold text-text md:text-h1">
            What a pack actually is
          </h2>
          <p className="mt-2 max-w-[60ch] text-body text-muted">
            Each pack is a file you own. ZIP of Markdown. Opens anywhere.
            No login, no dashboard, no subscription. The deliverable is a
            real artefact, dated at publish. The build spec, the GTM plan,
            the operations playbook, the QA report, every claim cited.
          </p>
          <p className="mt-4 max-w-[60ch] text-body text-muted">
            See one for free, no card, no email, on the{' '}
            <Link href="/sample" className={textLinkClass('font-medium')}>
              sample page
            </Link>
            . The same rigour that produced the catalogue produced it.
          </p>
        </div>

        <div className="mt-14 rounded-md border border-text bg-surface p-8">
     <p className="text-caption font-medium text-muted">
            Read before you buy
          </p>
          <h2 className="mt-2 text-h2 font-semibold text-text md:text-h1">
            See the work first.
          </h2>
          <p className="mt-2 max-w-[60ch] text-meta text-muted">
            Read a full report, unredacted. Every check, every verdict,
            every source link. If the rigour is what the page describes,
            the pack will be too.
          </p>
          <div className="mt-6">
            <Link
              href="/sample"
              className={buttonClasses({ size: 'lg' })}
            >
              Read the free report
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
        </div>
      </section>
    </MarketingLayout>
  );
}
