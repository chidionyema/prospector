import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, buttonClasses, textLinkClass } from '@/components/ui';
import { BRAND } from '@/lib/config';
import FounderNote from '@/components/marketing/FounderNote';
import { RESEARCH_STATS } from '@/lib/stats';
import { COMMON_CHECKS } from '@/lib/checks';

/**
 * L2 - The about page.
 *
 * The audit (§6) said the store was "a single voice" with no face. The
 * about page is the human face of the brand. It explains the engine, the
 * checks, the kill log, and the "source-or-die" voice. The story is
 * the moat; the page is the moat rendered as a person.
 */
export default function AboutPage() {
  // Via `RESEARCH_STATS`, not the raw JSON. This page was one of the seven that each imported
  // `kill-log-totals.json` and re-derived what the numbers meant; that is how "researched" ended
  // up printing the kill count elsewhere on the site. See lib/stats.ts.
  const totals = RESEARCH_STATS;
  return (
    <MarketingLayout>
      <Seo
        title={`About ${BRAND.name} - the engine behind the packs`}
        description={`How ${BRAND.name} works: an engine that tries to kill every business idea on cited evidence. ${totals.killed} killed, ${totals.survived} survived.`}
      />

      <section className="mx-auto max-w-3xl px-6 py-16 md:py-24">
    <p className="mb-3 text-caption font-medium text-muted">
          About
        </p>
        <h1 className="text-h1 font-semibold text-text md:text-display">
          We try to kill every idea.
        </h1>
        <p className="mt-4 max-w-[60ch] text-body leading-relaxed text-muted md:text-h2">
          {BRAND.name} is an engine that runs business ideas through a
          gauntlet of brutal checks. The ones that die on the first front
          where cited evidence is found against them are not listed. The
          ones that survive are the {BRAND.name} packs. Right now the kill
          count is{' '}
          <span className="font-semibold text-text">{totals.killed.toLocaleString('en-GB')}</span>
          {' '}and the survivors are{' '}
          <span className="font-semibold text-text">{totals.survived}</span>.
        </p>

        {/* The person, directly under the claim, and before the machinery.
            This page's own docblock has said since it was written that it is "the human face of
            the brand" and "the moat rendered as a person", and it named nobody -- 453 words about
            an engine. Renders nothing until `FOUNDER.name` is set in `lib/config.ts`, so the page
            is never worse than it was, and is materially better the moment a real name exists. */}
        <FounderNote variant="full" className="mt-10" />

        <div className="mt-12">
          <h2 className="text-h2 font-semibold text-text md:text-h1">
            The checks
          </h2>
          {/* The SUMMARY, not a second account. This section used to re-explain the mechanism at
              the same length /how-it-works does, so a visitor who read both got the filter
              described to them twice, in two different vocabularies, with no signal about which
              page was authoritative. /how-it-works is authoritative -- it shows a real kill under
              every check. This names the fronts and hands off, which is what an about page owes
              the reader. */}
          <p className="mt-2 max-w-[60ch] text-body text-muted">
            Every idea is attacked on the same fronts, and dies on the first
            one where cited evidence is found against it. A listed pack is one
            where no hard gate produced that evidence.
          </p>
          {/* Honest about the denominator. Measured 2026-08-06 against the live /catalog detail
              endpoint across all 63 published packs: 40 report "6/6 checks cleared", 15 "8/8",
              4 "7/8", 3 "9/9", 1 "6/8". Copy that promised "all six" was false for 23 of them,
              so this page names the six core fronts and then says plainly that some lanes run
              more (config.yaml `lanes.side_hustle` adds buyer_intent, currency and
              claims_verifiable). The per-pack truth is on the pack page, which has always
              rendered the engine's real numerator and denominator. */}
          <p className="mt-2 max-w-[60ch] text-body text-muted">
            These are common to every idea. Some face more: a small
            side-business idea is also tested on whether buyers are actively
            searching, whether the trend is still current, and whether its
            claims can be checked. Each pack page names the checks that idea
            faced and how many it cleared.
          </p>
          {/* Two columns from `sm` up. Six numbered cards holding three words and a short question
              each, stacked full width, ran the length of the viewport with most of every card
              empty (desktop-about-fold.png, 2026-08-06). Numbered order still reads correctly:
              CSS grid fills row-major, so 1-2 / 3-4 / 5-6. */}
          <ol className="mt-6 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
            {COMMON_CHECKS.map((check, i) => (
              <li key={check.id} className="flex items-start gap-3 rounded-md border border-border bg-surface p-4">
        <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-border bg-bg text-caption font-medium text-muted">
                  {i + 1}
                </span>
                <div>
                  <p className="text-meta font-semibold text-text">{check.name}</p>
                  <p className="mt-0.5 text-meta leading-relaxed text-muted">
                    {check.question}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-6 max-w-[60ch] text-body text-muted">
            That is the short version.{' '}
            <Link href="/how-it-works" className={textLinkClass('font-medium')}>
              How it works
            </Link>
            {' '}is the long one: every check above, with a real idea it killed and the
            sourced argument that killed it.
          </p>
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
          {/* Was disclosed nowhere but clause 6 of the refund policy. A shop whose whole pitch is
              "every claim traces to a source you can open" should say plainly what does the
              tracing, in the same place it makes that pitch, not bury it in legal fine print --
              the gap between the two is exactly what a reader who trusts the site is trusting. */}
          <p className="mt-4 max-w-[60ch] text-body text-muted">
            The research is done by an AI pipeline, not a person typing an opinion. It is built to
            argue against every idea it is given, using only passages it actually retrieves from
            the open web: no claim ships without a link to where it came from, and an idea with no
            evidence against it is not proof the idea is good, just that the pipeline could not
            find the evidence yet. That is what &quot;every claim traces to a source&quot; means in
            practice, and it is why the process is adversarial rather than generative.
          </p>
        </div>

        <div className="mt-12">
          <h2 className="text-h2 font-semibold text-text md:text-h1">
            What a pack actually is
          </h2>
          {/* Was "Each pack is a file you own. ZIP of Markdown. Opens anywhere." -- three sentences
              about the container before a single word about what is in it. The documents lead now;
              the format is the last clause, where it belongs. */}
          <p className="mt-2 max-w-[60ch] text-body text-muted">
            A build spec, a go-to-market plan, an operations playbook and a QA report, with a
            citation behind every claim and a date stamped at publish. Yours outright: no login, no
            dashboard, no subscription, and plain text files you can open anywhere.
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
