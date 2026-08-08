import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses, Glyph, Icon, SourceChipRow } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { Section, SectionBand } from '@/components/marketing/blocks';
import { WaitlistCallout } from '@/components/waitlist/WaitlistCallout';
import DocRail, { type DocSectionRef } from '@/components/marketing/DocRail';
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
        'inline-flex flex-none items-center gap-1.5 rounded-sm px-2.5 py-1 text-caption font-medium',
        supported ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning',
      )}
    >
      {/* §3.3: a check's ruling is drawn by the verdict set, never by the lucide sheet. The two
          marks differ by SHAPE (filled square vs. left-half filled), so the badge still says
          which way the check went when the colour is stripped -- printed, or read by someone who
          cannot separate the green from the amber. */}
      <Glyph name={supported ? 'survived' : 'pushed-back'} />
      {supported ? 'Survived' : 'Pushed back'}
    </span>
  );
}

/*
  THE DOCUMENT MODEL, HOISTED TO MODULE SCOPE.

  `sample-report.json` is a static import, so every derived fact below is knowable before render and
  none of it can change between renders. That is not a micro-optimisation here, it is a correctness
  requirement: `DocRail` observes the document in a `useEffect` keyed on the `sections` array, and
  an array rebuilt on every render would tear down and re-create the IntersectionObserver each time
  the rail set its own active-section state. Hoisting makes the identity stable by construction
  rather than by remembering to memoise.
*/
const CHECKS = report.checks as Check[];
const SCORES = report.scores as Record<string, number>;
const AXES = Object.entries(AXIS_LABELS).filter(([k]) => k in SCORES);
/* Counted from the checks themselves, never from `report.total - report.supported`. The JSON's
   `total` is what produced the "7 of 8" fraction this page no longer states, and a derived count
   that disagrees with the rendered rows is exactly the kind of drift the fraction caused. */
const PUSHED_BACK = CHECKS.filter((c) => c.verdict !== 'supported').length;
const FIRST_PUSHBACK = CHECKS.findIndex((c) => c.verdict !== 'supported');
const HAS_COUNTER = Boolean(report.premortem.strongestAlternative || report.adversarial.killCase);

/* The first pushed-back check keeps the `pushback` id, because the hero has linked to `#pushback`
   since before the rail existed and that anchor is the most valuable link on the page. An element
   has one id, so the rest are keyed by the engine's own check key. */
function checkAnchor(index: number): string {
  return index === FIRST_PUSHBACK ? 'pushback' : `check-${CHECKS[index].key}`;
}

/* Every check is listed individually rather than as one "Every check" entry. The rail is where the
   reader learns the document's shape, and the shape of this document is eight named attacks with
   one of them pushing back. Collapsing them to a single line hides both the count and the
   objection, which are the two facts most worth finding. */
const SECTIONS: DocSectionRef[] = [
  { id: 'opportunity', label: 'The opportunity' },
  ...(AXES.length > 0 ? [{ id: 'scored', label: 'The stress test, scored' }] : []),
  { id: 'checks', label: `Every check (${CHECKS.length})` },
  ...CHECKS.map((check, i): DocSectionRef => ({
    id: checkAnchor(i),
    label: check.name,
    nested: true,
    ...(check.verdict === 'supported'
      ? { note: 'ok' }
      : { note: 'pushed back', tone: 'kill' as const }),
  })),
  ...(HAS_COUNTER ? [{ id: 'counter', label: 'The case against it' }] : []),
  { id: 'buy', label: 'Every pack is built like this' },
];

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
  // The markup is `SourceChipRow` now. Everything the docblock above argues for survives the move
  // -- domain first, mono, title in sans behind it -- but this page no longer owns a private copy
  // of it. That copy was one of five, and the fifth is how "the domain leads" became true on
  // /sample and false in the hero.
  return (
    <SourceChipRow
      sources={sources.map((s) => ({ url: s.url, host: s.domain, label: s.label }))}
      className="mt-4 border-t border-border pt-4"
    />
  );
}

export default function SamplePage() {

  return (
    <MarketingLayout>
      {/* Its own description, not the site default. /sample served the homepage's generic
          "Mumchimp sells grounded business opportunity packs..." blurb, so the one page offering
          a free full report had a search snippet that never mentioned it was free, was a sample,
          or needed no card. That is the page most worth clicking and it was described as the
          shop in general. */}
      <Seo
        title="Report #00, free. A complete stress-tested business report, nothing held back."
        description="Read a complete Mumchimp report free, unredacted: every check, every verdict, and a clickable source behind every claim. No card, no email, no signup. If the rigour here is real, the packs are the same."
      />

      {/* Hero. Left-aligned, like every other marketing hero on the site.
          This one was hand-rolled with `text-center` and a stack of `mx-auto`s, so /sample -- the
          page whose entire job is "here is the evidence, judge us" -- was the only page in the set
          that centred its headline and a 60ch paragraph (desktop-sample-fold.png vs
          desktop-about-fold.png, 2026-08-06). `PageHero` had already recorded why that is wrong
          (blocks.tsx:61): a centred ragged-both-edges paragraph starts every line at a different x.
          The rule existed; this page just was not using the component that carried it. */}
      {/* `7xl` and the rail grid, matching the report band below, so this page has ONE left edge.
          It was `6xl` with no grid: the headline then started at the 6xl margin while every line of
          the report started at the 7xl margin plus the 14rem rail, which is the two-left-margins
          defect `storefrontDesignContract` was written to catch. Widening the band alone does not
          fix it (the report is still inset by the rail), so the hero takes the same grid with an
          empty rail column and the two columns line up. */}
      <SectionBand bg="white" width="7xl" className="pt-14 pb-8 md:pt-20 md:pb-10">
        <div className="lg:grid lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-14">
          <div aria-hidden />
          <div className="min-w-0">
        <p className="mb-4 text-caption font-medium text-muted">
          Report #00 · The free sample
        </p>
        {/* WAS "Don't trust us? Read a whole report for zero pence."
            It opens by putting the accusation in the reader's mouth. Most people arriving here have
            no opinion of us yet; the sentence hands them one, and the one it hands them is
            suspicion. "Zero pence" is the same reflex in the price: a shop that will not simply say
            "free" sounds like it is bracing for an argument.
            The headline states what the thing IS. The reader can decide what it proves. */}
        <h1 className="max-w-[20ch] text-balance text-h1 font-semibold text-text md:text-display">
          A whole report. Free, and nothing held back.
        </h1>
        <p className="mt-6 max-w-[60ch] text-body leading-relaxed text-muted">
          One complete pack, exactly as a buyer receives it: the opportunity, who pays, the numbers,
          every check, and the sources behind each one. Including the objection this idea did not
          fully answer.
        </p>
        {/* WAS "7 of 8 checks survived", and it read as a fail.
            A score with a denominator is an exam mark, and a shop that says "listed only once it
            clears every check" on its home page then opened its flagship free sample with a mark of
            7/8. The reader's only available conclusion is that we published something that failed
            one -- so the page built to answer "can I trust these people" was the page that raised
            the doubt.

            Both numbers were always true; the framing was the bug. The seven are the gates, and all
            seven cleared. The eighth is the adversarial claim-check, and it pushed back: the engine
            found an existing snagging-survey service that contradicts part of the pitch, cited it
            (snagged.co.uk), and the pack shipped WITH that objection attached. Publishing the
            objection is the entire product; scoring it as a lost mark out of eight buried it.

            Stated as two facts rather than one fraction, and the second one is a link, because the
            objection is the most persuasive thing on this page. */}
        <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-2 text-meta font-semibold text-muted">
          {/* §3.3 (2026-08-08): four lucide glyphs used to sit on this strip -- a tick, a shield,
              a badge-check and a calendar -- and all four were labelling ENGINE OUTPUT. Three are
              now the verdict marks. The fourth, the calendar beside the freshness date, has no
              equivalent among the six and is simply gone: the date is engine output, so it reads
              in the mono face, and a decorative calendar next to a date says nothing the date has
              not already said. */}
          <span className="inline-flex items-center gap-2">
            <Glyph name="survived" className="text-success" />
            {report.supported} checks cleared
          </span>
          {PUSHED_BACK > 0 && (
            <a
              href="#pushback"
              className="inline-flex items-center gap-2 text-warning underline-offset-2 hover:underline"
            >
              <Glyph name="pushed-back" />
              {PUSHED_BACK === 1 ? '1 objection we could not dismiss' : `${PUSHED_BACK} objections we could not dismiss`}
            </a>
          )}
          <span className="inline-flex items-center gap-2">
            <Glyph name="source" className="text-success" />
            {report.sourceCount} cited sources
          </span>
          {freshnessLabel(report.verifiedAt) && (
            <span className="inline-flex items-center gap-2">
              {freshnessLabel(report.verifiedAt)}
            </span>
          )}
        </div>
          </div>
        </div>
      </SectionBand>

      {/*
        THE READING APPLICATION.

        `7xl`, the same band the hero above declares. The rail is new width, and taking it out of
        the old measure would have narrowed the document itself; the band grew by roughly the width
        of the rail so the report column keeps the measure it already had, and every paragraph
        inside it keeps its own `max-w-[68ch]` cap regardless.

        `lg:` and above only. Below that the rail does not render at all (see `DocRail`) and the
        grid collapses to the single column this page has always been, so nothing about the mobile
        reading experience changes.
      */}
      <Section bg="bg" width="7xl" className="!pt-6 !pb-24">
        <div className="lg:grid lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-14">
          <DocRail sections={SECTIONS} eyebrow="Report #00 · contents" />
          <div className="min-w-0">
        {/* The idea */}
        <div id="opportunity" className="scroll-mt-24 rounded-md border border-border bg-surface p-7 md:p-9">
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
        {AXES.length > 0 && (
          <div id="scored" className="mt-10 scroll-mt-24">
            <h2 className="text-h2 font-semibold text-text">The stress test, scored</h2>
            <p className="mt-2 max-w-[60ch] text-meta text-muted">
              Scored on six axes out of five. The weak bars are shown too. That is the point.
            </p>
            <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
              {AXES.map(([key, label]) => {
                const v = SCORES[key];
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
                          className={cx('h-1.5 flex-1 rounded-sm', i < v ? tone : 'bg-border')}
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
        <div id="checks" className="mt-10 scroll-mt-24">
          <h2 className="text-h2 font-semibold text-text">Every check, every source</h2>
          {/* The second sentence exists to answer the question the amber row below provokes and
              previously left hanging: "one of these failed, so why are you selling it?" The answer
              is that a hard gate failing stops a pack from ever being listed, and this one is not a
              hard gate -- it is the adversarial pass, whose job is to find the best argument
              against an idea that already cleared the gates. Left unanswered, the reader supplies
              the worse explanation. */}
          <p className="mt-2 max-w-[64ch] text-meta text-muted">
            Each gate is an attack the idea had to survive. Fail a gate and a pack is never listed
            at all. The amber one below is not a gate: it is the adversarial pass, and what it found
            ships with the report instead of being quietly dropped. Open any source and read it
            yourself. None of this is our opinion; it is what the pages actually said.
          </p>
          <ul className="mt-6 list-none space-y-4 p-0">
            {CHECKS.map((ch, i) => (
              <li
                key={i}
                /* The FIRST pushed-back check carries the `#pushback` anchor the hero links to,
                   and the whole card is tinted rather than only its badge. A reader who clicks
                   "1 objection we could not dismiss" has to land on something that looks like the
                   thing they clicked; scrolling them to a row identical to the seven above it
                   makes the link feel broken. `scroll-mt-24` clears the sticky header. */
                id={checkAnchor(i)}
                className={cx(
                  'rounded-md border p-5 md:p-6 scroll-mt-24',
                  ch.verdict === 'supported'
                    ? 'border-border bg-surface'
                    : 'border-warning/30 bg-warning/5',
                )}
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
          <div id="counter" className="mt-10 scroll-mt-24 rounded-md border border-warning/30 bg-warning/5 p-7 md:p-9">
            <div className="flex items-center gap-2">
              <Glyph name="pushed-back" className="text-warning" />
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
        <div id="buy" className="mt-12 scroll-mt-24 rounded-md border border-border bg-surface p-8 text-center md:p-10">
          <h2 className="mx-auto max-w-[24ch] text-balance text-h2 font-semibold text-text md:text-h1">
            That was free. Every pack on the shelf is built like this.
          </h2>
          <p className="mx-auto mt-3 max-w-[56ch] text-body leading-relaxed text-muted">
            A pack adds the build spec, the go to market plan, and the operations playbook on top of the
            evidence record you just read. One payment, yours to keep.
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
          </div>
        </div>
      </Section>
    </MarketingLayout>
  );
}
