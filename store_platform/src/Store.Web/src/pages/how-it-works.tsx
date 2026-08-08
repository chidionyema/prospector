import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { buttonClasses, Icon, textLinkClass } from '@/components/ui';
import { useCopyVariant } from '@/lib/useCopyVariant';
import { COMMON_CHECKS, idsFor, type Check } from '@/lib/checks';
import { RESEARCH_STATS } from '@/lib/stats';
import CheckSequence from '@/components/marketing/CheckSequence';
/* `kill-log-examples.json`, NOT the full `kill-log.json`. This page draws ONE illustrative kill per
   check and needs the whole record (reason, citations), so the names file is not enough. The
   examples file is `entries[:60]` with every field intact -- byte-for-byte what `kill-log.json`
   held before the log was raised from 60 to 400 records for the /kill-log instrument -- so which
   example each check picks is unchanged, while the 452 KB full log stays out of this bundle. A
   static JSON import is one value and cannot be tree-shaken. */
import killLog from '@/data/kill-log-examples.json';
import killTotals from '@/data/kill-log-totals.json';

/** One entry from the kill log picked to illustrate a specific gate. */
interface KillExample {
  title: string;
  gate: string;
  gateLabel: string;
  reason: string;
}

/**
 * The curated illustration for each check, keyed by the engine's gate id.
 *
 * The buyer-facing NAME is deliberately not in this table any more -- it comes from
 * `COMMON_CHECKS`. This page used to carry its own, which is how one gate ended up with three
 * names across the site: `payer_solvency` was "Payer can actually pay" here, "Someone will pay"
 * on /about and "Whether anyone will actually pay" on the pack page. Only the example is a
 * property of this page; the vocabulary is not.
 */
const EXAMPLE_TITLES: Record<string, string> = {
  pain_reality: 'NI-GapSweep',
  value_durability: 'DecibelKit',
  incumbency: 'SaltCourt',
  payer_solvency: 'SplitCare',
  distribution: 'AssessAid',
  legality: 'GasSafe',
};

/**
 * The illustration for one gate: the curated kill if it is still in the log, otherwise any kill
 * that died on that gate.
 *
 * The curated title was the ONLY lookup, and two of the six had already fallen out of the published
 * log -- `NI-GapSweep` and `GasSafe` (2026-08-06). So the page that exists to prove the filter is
 * real printed "No example found in the kill log for this gate." twice, under checks 1 and 6, on
 * two gates the log has 2 and 3 real kills for:
 *
 *   python3 -c "import json,collections;d=json.load(open('src/data/kill-log.json'));\
 *   print(collections.Counter(e['gate'] for e in d['entries']))"
 *   -> Counter({'incumbency': 30, 'payer_solvency': 12, 'value_durability': 10, 'legality': 3,
 *               'pain_reality': 2, 'distribution': 2, 'route_to_market': 1})
 *
 * A hand-picked title is a dangling reference to data the engine rewrites on every batch, and it
 * fails silently and in public. The curated pick stays because a chosen example reads better than
 * an arbitrary one; it is now a preference, not the only path.
 *
 * `distribution` also accepts `route_to_market`: the engine emits two keys for that one check and
 * both carry the same buyer-facing label. That alias list now lives on the check itself
 * (`lib/checks.ts`), so it is stated once for the whole site rather than per page.
 */
function findExample(check: Check, titleFragment: string): KillExample | undefined {
  const entries = killLog.entries as KillExample[];
  const curated = entries.find((e) => e.title.toLowerCase().includes(titleFragment.toLowerCase()));
  if (curated) return curated;
  const keys = idsFor(check);
  return entries.find((e) => keys.includes(e.gate));
}

/**
 * The gate id to print under the heading. When the curated example died on one of this check's
 * ids, print THAT one, so the identifier on screen is the identifier that actually fired for the
 * kill shown directly beneath it. Otherwise print the check's primary id.
 */
function gateIdFor(check: Check, example: KillExample | undefined): string {
  if (example && idsFor(check).includes(example.gate)) return example.gate;
  return check.id;
}

/**
 * The example's reason, cut at a SENTENCE boundary, never mid-word.
 *
 * This used to be `slice(0, 160)` with the tail word trimmed and an ellipsis bolted on, so the six
 * cards that carry the only evidence on the page each ended in a hanging clause and a "…". On the
 * page whose subject is that our arguments are complete and checkable, an argument visibly cut off
 * halfway is the wrong thing to show, and the ellipsis says "there is more we are not telling you"
 * directly under a heading promising the opposite.
 *
 * So: take whole sentences while they fit. If even the first sentence is over the budget, print
 * that whole sentence anyway. The card is then always a complete thought, and the length varies by
 * a line or two, which is a cheaper cost than an amputated one.
 */
function firstSentences(reason: string, budget: number): string {
  const text = reason.trim();
  if (text.length <= budget) return text;
  // Split after ., ! or ? followed by whitespace. Keeps the terminator on the sentence.
  const sentences = text.match(/[^.!?]+[.!?]+(\s|$)|[^.!?]+$/g) ?? [text];
  let out = '';
  for (const sentence of sentences) {
    const next = (out + sentence).trimEnd();
    if (out && next.length > budget) break;
    out = next;
    if (out.length >= budget) break;
  }
  return out || text;
}

export default function HowItWorks() {
  const { variant } = useCopyVariant();
  const totals = killTotals as { killed: number; passed: number };
  return (
    <MarketingLayout>
      <Seo
        title="How it works"
        description={variant.howItWorksSeoDescription}
      />

      <PageHero
        width="6xl"
        eyebrow={variant.howItWorksEyebrow}
        title={variant.howItWorksTitle}
        lead={variant.howItWorksLead}
      />

      {/*
        THE STAT, PROMOTED TO POSITION 2 (email §2).
        The page's thesis in one line: of every idea that entered, this many survived, and the
        rejects are public. The number used to be buried at the bottom of the page under "Why
        most ideas die", so a reader who scrolled the methodology and the worked example still
        had not met the single fact the page exists to prove.

        `RESEARCH_STATS` is the same source the home page proof strip uses, so the two pages
        cannot disagree. `rejectRate` is computed once, in `lib/stats.ts`, and never re-rounded
        on this page.
      */}
      <Section
        bg="bg"
        width="6xl"
        className="!py-10 md:!py-12"
      >
        <div className="max-w-3xl">
          <p className="text-body font-semibold leading-relaxed text-text">
            {RESEARCH_STATS.researched.toLocaleString('en-GB')} ideas in. {RESEARCH_STATS.survived.toLocaleString('en-GB')} out.
          </p>
          <p className="mt-2 max-w-[60ch] text-meta leading-relaxed text-muted">
            {RESEARCH_STATS.rejectRate}% survive. Every kill is published with the evidence that
            made it.
          </p>
        </div>
      </Section>

      {/*
       * A. THE CHECK SEQUENCE, and it goes first.
       *
       * The page opened on an abstract description of the filter and then showed six unrelated
       * ideas dying on six different gates. Nothing on it showed a single idea going through the
       * checks in order, which is the one thing the page is named after. A reader could finish it
       * knowing the gates exist and still not know what a run looks like.
       *
       * So a real evidence record runs first, then the gate-by-gate kills. The order is the argument:
       * here is the machine working on one subject you can audit; here is the same machine when
       * the subject does not survive. Reversing them puts six disconnected failures in front of
       * the reader before they have seen a single complete run.
       */}
      <Section
        bg="white"
        width="6xl"
        title="One idea, all the way through"
        intro="Every pack on the shelf carries an evidence record like this. The one below is real, it is the free sample, and every source in it opens."
      >
        <CheckSequence />
      </Section>

      {/* B. The checks, as a stepped timeline */}
      <Section
        bg="bg"
        width="6xl"
        title="Six checks, in order. One hard fail and it stops."
        intro="Some ideas face more checks; each pack page names its own. Every kill is logged with its reason, so the filter is auditable, not a black box."
      >
        {/* THE AI DISCLOSURE, AND THIS PAGE OWNS IT.
            It was disclosed nowhere but clause 6 of the refund policy and, until 2026-08-07, a
            paragraph on /about that told the same fact in different words. Inconsistent disclosure
            across a site reads as evasive, so it is stated ONCE, here, on the page that explains
            the mechanism, and the home page and /about say nothing about mechanism and link here.
            One sentence, before the first check, because a reader who learns this after reading
            six verdicts has been told late. */}
        <p className="mb-10 max-w-3xl text-body leading-relaxed text-muted">
          Every check below is run by an AI agent rather than by a person forming an opinion: the
          agent may rule only on passages it fetched from the open web, and the sources it used are
          published with the verdict.
        </p>
        {/* No `mt-12`: the lede moved into the heading block, whose `mb-10` is now the gap to the
            content. Keeping both stacked 88px between the lede and step 1. */}
        <div>
          {COMMON_CHECKS.map((check, i) => {
            const example = findExample(check, EXAMPLE_TITLES[check.id] ?? '');
            const last = i === COMMON_CHECKS.length - 1;
            return (
              <div
                key={check.id}
                // `pb-8` on the row, not `space-y-8` on the list. The connector below is
                // `flex-1` inside this row, so it can only grow to the row's own height: with the
                // gap living OUTSIDE the row, the rail stopped at each card's bottom edge and
                // restarted 32px lower at the next badge, rendering the timeline as six detached
                // segments (desktop-how-it-works-fold.png, 2026-08-06). Moving the gap inside the
                // row makes it rail height the connector can occupy.
                className={`relative flex gap-6${last ? '' : ' pb-8'}`}
              >
                {/* Step number + vertical line */}
                <div className="flex flex-col items-center flex-none">
                  <span className="flex h-10 w-10 items-center justify-center rounded-md bg-text text-meta font-semibold text-bg">
                    {i + 1}
                  </span>
                  {!last && (
                    // `-mb-8` cancels the row's `pb-8`. `flex-1` grows to the flex CONTENT box,
                    // which excludes padding, so `pb-8` alone still left the rail 32px short of
                    // the next badge (measured 32px on all five joins, 2026-08-06). The negative
                    // margin lets the rail's box run through the padding to meet it.
                    <div className="mt-2 -mb-8 w-0.5 flex-1 bg-border/60" />
                  )}
                </div>

                {/* Card body. `max-w-3xl` is the measure the section intro directly above already
                    uses: without it the example card filled the 6xl band and set its reason on a
                    ~130-character line, so the page asked the reader to change measure between the
                    paragraph explaining the gates and the evidence for each one
                    (desktop-how-it-works-fold.png, 2026-08-06). */}
                <div className="max-w-3xl flex-1 pb-6">
                  <h2 className="text-h2 font-semibold text-text leading-tight">
                    {check.name}
                  </h2>
         <p className="mt-1 text-caption font-medium text-muted">
                    <code className="bg-bg px-1.5 py-0.5 rounded-md text-caption">{gateIdFor(check, example)}</code>
                  </p>

                  {example && (
                    <div className="mt-5 rounded-md border border-border bg-bg/40 p-5">
           <p className="text-caption font-medium text-muted">
                        {example.gateLabel}
                      </p>
                      <h3 className="mt-2 text-meta font-semibold text-text leading-snug">
                        {example.title}
                      </h3>
                      <p className="mt-2 text-meta leading-relaxed text-muted">
                        {firstSentences(example.reason, 160)}
                      </p>
                      <Link
                        href="/kill-log"
                        className="mt-2 inline-flex items-center gap-1 text-caption font-semibold text-accent transition-colors hover:text-accent-hover"
                      >
                        See kill‑log <Icon name="arrowRight" size={12} />
                      </Link>
                    </div>
                  )}

                  {/* No `else`. If the log genuinely holds no kill for a gate, the gate's own
                      description still stands on its own and the absence is not worth a sentence.
                      The line that used to sit here, "No example found in the kill log for this
                      gate.", told a buyer on the page that argues the filter is real that we had
                      no evidence of it -- and said so because of a stale hardcoded title, not
                      because the evidence was missing. */}
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      {/* C. The adversarial pass */}
      <Section
        bg="white"
        width="6xl"
        title="Then a second agent attacks the survivor."
      >
        <div className="max-w-3xl space-y-4">
          <p className="text-body font-normal leading-relaxed text-muted">
            It hunts for contradictions, weak citations, and gaps the first pass missed. The
            evidence record survives only if every objection is answered by evidence already on file.
            No new research, no hand-waving.
          </p>
          <p className="text-meta leading-relaxed text-muted">
            Silence in the record means <em>unverifiable</em>, never <em>false</em>. The agent only
            rules on pages it actually fetched.
          </p>
        </div>
      </Section>

      {/* D. The graveyard -- now collapsed: the stat already lives at position 2 of this
          page, so what stood here is a duplicate of the page's thesis, and the "auditable, not
          a black box" line above already says what the kill-log link is for. A single link to
          the log is the only thing missing. */}
      <Section
        bg="bg"
        width="6xl"
        title="The kill log"
      >
        <div className="max-w-3xl space-y-6">
          <p className="text-body leading-relaxed text-muted">
            Every kill is published in full, with the check that fired and the sourced argument
            that killed it.
          </p>
          <Link
            href="/kill-log"
            className={buttonClasses({ size: 'lg' })}
          >
            See the {totals.killed.toLocaleString()} we killed{' '}
            <Icon name="arrowRight" size={15} />
          </Link>
        </div>
      </Section>

      {/* E. Honest limits, ONE LINE, and then the page that owns them.
          /pricing is the sitewide owner of "what you do not get": it lists all four limits (no
          guarantee of success, no live updates, no coaching, no subscription or seat) beside the
          price they qualify, which is where a buyer is actually deciding. A second, softer account
          of the same limits here meant the honest bit was said twice and in full nowhere. */}
      <Section
        bg="white"
        width="6xl"
        title="The honest limits"
      >
        <div className="max-w-3xl">
          <p className="text-body font-normal leading-relaxed text-muted">
            A pack is evidence-backed research, not a guarantee. The finding, vetting and sourcing
            is done. The execution is yours. No analysis can promise a business outcome.
          </p>
        </div>
      </Section>

      <CtaBand
        width="6xl"
        title="See what made it through."
        lead=""
        primary={{ href: '/', label: 'Browse the packs' }}
        secondary={{ href: '/sample', label: 'Read the free sample first' }}
      />
    </MarketingLayout>
  );
}
