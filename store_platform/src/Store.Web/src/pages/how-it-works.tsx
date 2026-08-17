import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand, HeroList } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { buttonClasses, Icon } from '@/components/ui';
import { useCopyVariant } from '@/lib/useCopyVariant';
import { COMMON_CHECKS, idsFor, type Check } from '@/lib/checks';
import { RESEARCH_STATS, killsSummary } from '@/lib/stats';
import { plainEnglish } from '@/lib/plainEnglish';
import { PACK_DISCLAIMER, PACK_SCOPE } from '@/lib/disclaimer';
import CheckSequence from '@/components/marketing/CheckSequence';
import FunnelDiagram from '@/components/marketing/FunnelDiagram';
/* `kill-log-examples.json`, NOT the full `kill-log.json`. This page draws ONE illustrative kill per
   check and needs the whole record (reason, citations), so the names file is not enough. The
   examples file is `entries[:60]` with every field intact -- byte-for-byte what `kill-log.json`
   held before the log was raised from 60 to 400 records for the /kill-log instrument -- so which
   example each check picks is unchanged, while the 452 KB full log stays out of this bundle. A
   static JSON import is one value and cannot be tree-shaken. */
import killLog from '@/data/kill-log-examples.json';

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
  return (
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'How it works' }]}
      breadcrumbsWidth="6xl"
    >
      <Seo
        title="How it works"
        description={variant.howItWorksSeoDescription}
      />

      {/* THE ASIDE IS THE ATTACK LIST, and it is `refutation`, not `name`, on purpose.
          The headline says every idea faces checks built to kill it, and until now the reader had
          to scroll past a stat, a worked example and a disclosure before learning what any of them
          were. `name` would have been a table of contents for the timeline below and would read as
          the same list printed twice. `refutation` is the other face of each check -- the thing the
          agent is trying to PROVE -- so the column states what the headline asserts, in the
          headline's own register, while the timeline below keeps the names, the questions and the
          worked kills. One vocabulary source either way: `COMMON_CHECKS`, which exists because this
          page once carried its own and gave one gate three names across the site. Ordered, because
          the run really is a sequence and it stops at the first hard failure. */}
      <PageHero
        width="6xl"
        eyebrow={variant.howItWorksEyebrow}
        title={variant.howItWorksTitle}
        lead={variant.howItWorksLead}
        aside={
          <HeroList
            label="What each agent tries to prove"
            ordered
            items={COMMON_CHECKS.map((c) => c.refutation)}
          />
        }
      />

      {/*
        THE STAT, PROMOTED TO POSITION 2 (email §2).
        The page's thesis in one line: of every idea that entered, this many survived, and the
        rejects are public. The number used to be buried at the bottom of the page under "Why
        most ideas die", so a reader who scrolled the methodology and the worked example still
        had not met the single fact the page exists to prove.

        `RESEARCH_STATS` is the same source the home page proof strip uses, so the two pages
        cannot disagree. The rate is computed once, in `lib/stats.ts`, and never re-rounded here.
        There is only ONE rate now, the kill rate: this line read "1,444 ideas in. 80 out." over
        "5.5% survive", and both halves stated a survivor population of 80 against a shelf of 50.
        The founder cut the figure on 2026-08-13 rather than have the copy keep explaining it, so
        the thesis is stated from the kill side, which is the side we can show you.
      */}
      <Section
        bg="bg"
        width="6xl"
        className="!py-10 md:!py-12"
      >
        {/* THE STAT NOW HAS ITS PICTURE BESIDE IT (brief 2026-08-15, Part Four: "there is a funnel
            in the logo mark and a funnel in the proposition, and it currently appears as
            neither"). `FunnelDiagram` reads the SAME `RESEARCH_STATS` this paragraph reads, so the
            two cannot drift, and it prints no third figure -- the taper is to scale and the stub
            is unlabelled, for the reason its docblock gives at length. One diagram in this
            section and no other, per the brief's density rule. */}
        <div className="grid gap-8 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-12">
          <div className="max-w-3xl">
            <p className="text-body font-semibold leading-relaxed text-text">
              {RESEARCH_STATS.researched.toLocaleString('en-GB')} ideas in.{' '}
              {RESEARCH_STATS.killed.toLocaleString('en-GB')} killed.
            </p>
          {/* This line promised that EVERY kill ships published with the evidence behind it, which
              was false about a number this page reads from the same JSON as the page that states it
              correctly: 400 of the 1,364, per /kill-log. The replacement claims no quantity at all,
              and `numbersReconcile.test.ts` scans every page for the absolute form. */}
            <p className="mt-2 max-w-[60ch] text-meta leading-relaxed text-muted">
              {RESEARCH_STATS.rejectRateLabel} died on cited evidence. {killsSummary()}.
            </p>
          </div>
          <FunnelDiagram className="w-full md:w-[340px]" />
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
        intro="Every pack carries an evidence record like this one. It is the free sample, and every source in it opens."
      >
        <CheckSequence />
      </Section>

      {/* B. The checks, as a stepped timeline.

          Through the copy dictionary, NOT literals. Hardcoding the email's wording here orphaned
          `sixChecksTitle` / `sixChecksDescription` in all three variants of `lib/copyConfig.ts`:
          the A/B mechanism went dead for this section without the change saying so, and
          `fixedCheckCount.test.ts`'s "every copy variant intros the timeline with a hedge" kept
          passing over strings no page rendered any more. Variant a carries the email's wording. */}
      <Section
        bg="bg"
        width="6xl"
        title={variant.sixChecksTitle}
        intro={variant.sixChecksDescription}
      >
        {/* THE AI DISCLOSURE, AND THIS PAGE OWNS IT.
            It was disclosed nowhere but clause 6 of the refund policy and, until 2026-08-07, a
            paragraph on /about that told the same fact in different words. Inconsistent disclosure
            across a site reads as evasive, so it is stated ONCE, here, on the page that explains
            the mechanism, and the home page and /about say nothing about mechanism and link here.
            Before the first check, because a reader who learns this after reading six verdicts has
            been told late. The 52-word single sentence it started as was three claims sharing one
            spine; three short sentences say the same thing and can each be read on its own. */}
        <p className="mb-10 max-w-3xl text-body leading-relaxed text-muted">
          AI agents run the checks below. Each may only rule on passages it fetched from the open
          web, and those sources are published with the verdict, so you can hold the reasoning
          against them yourself. A person reads that record before a pack reaches the shelf.
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
                  {/* THE GATE ID IS GONE FROM THIS PAGE. It was a mono `<code>` chip reading
                      `pain_reality` sitting directly under the heading that already says "Real
                      pain"; de-underscoring it to "pain reality" was the first attempt and the
                      founder read the same complaint back off the page a second time
                      (2026-08-15: "still seeing ... payer_solvency, value_durability ... why am I
                      repeating myself"). A machine identifier restated as a label is still a
                      machine identifier, and it told a buyer nothing the heading had not already
                      said. Nothing is lost: the kill-log example directly below prints that gate's
                      real verdict wording in `example.gateLabel`, which is the phrase a reader
                      will meet again on /kill-log. */}

                  {example && (
                    <div className="mt-5 rounded-md border border-border bg-bg/40 p-6">
           <p className="text-caption font-medium text-muted">
                        {example.gateLabel}
                      </p>
                      <h3 className="mt-2 text-meta font-semibold text-text leading-snug">
                        {example.title}
                      </h3>
                      <p className="mt-2 text-meta leading-relaxed text-muted">
                        {firstSentences(plainEnglish(example.reason), 160)}
                      </p>
                      <Link
                        href="/kill-log"
                        className="mt-2 inline-flex items-center gap-1 py-[13px] text-caption font-semibold text-accent transition-colors hover:text-accent-hover"
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

      {/* C. The adversarial pass.
          PLURAL, here and everywhere (founder, 2026-08-15: "an agent should be agents, also across
          the site, plural not singular agent"). The work is a fleet, and the singular undersold it
          as one model having a think. */}
      <Section
        bg="white"
        width="6xl"
        title="Then a second wave of agents attacks the survivor."
      >
        <div className="max-w-3xl space-y-4">
          <p className="text-body font-normal leading-relaxed text-muted">
            They hunt for contradictions, weak citations, and gaps the first pass missed. The
            evidence record survives only if every objection is answered by evidence already on file.
            No new research, no hand-waving.
          </p>
          <p className="text-meta leading-relaxed text-muted">
            Silence in the record means <em>unverifiable</em>, never <em>false</em>. The agents only
            rule on pages they actually fetched.
          </p>
          {/* MASTER-BRIEF §5.3. "Pushed back" is on the homepage hero, on the check list under it,
              on /sample and on every pack page, and until now no page said what it meant. A reader
              met a third verdict word beside "survived" and "killed" and had to guess whether it
              was a soft failure. It is not. This is the page that explains the process, and this
              paragraph is where the same idea already lives, so the definition goes here rather
              than in a fourth place. */}
          <p className="text-meta leading-relaxed text-muted">
            A check that is <em>pushed back</em> is that silence with a name. The evidence would not
            settle the question either way, so the idea carried on and the doubt stayed on the
            record for you to read. It is drawn in amber, never red. Red means killed.
          </p>
        </div>
      </Section>

      {/* C2. THE HUMAN PASS, and it was missing entirely.
          Founder, 2026-08-15: "we need to be firm on our messaging, AI and automation led, human
          review and verification", and on this page specifically "no mention of human reviewer and
          researcher". `rg -i 'human|review|researcher|analyst|by hand|manual'` over this file
          returned NOTHING: the page described two agents and went straight to the kill log, so the
          step a buyer most wants to hear about was the one step never stated.

          It sits AFTER the adversarial pass because that is where it happens -- a person reviewing
          an unchallenged record is reviewing less than the machine already did.

          The claim is deliberately narrow. "A person reviews the record and can reject it" is true
          and checkable; "every pack is hand-researched" would not be, and this is the page that
          exists to not overclaim. */}
      <Section
        bg="bg"
        width="6xl"
        title="Then a person reviews it."
      >
        <div className="max-w-3xl space-y-4">
          <p className="text-body font-normal leading-relaxed text-muted">
            Automating the finding, the checking and the sourcing is what lets every idea get the
            same treatment, instead of the handful a person could read. But nothing reaches the
            shelf on its own: a person reads the verdict, opens the sources, and checks the
            argument holds before a pack is published.
          </p>
          <p className="text-meta leading-relaxed text-muted">
            The reviewer can send a pack back or kill it outright. What they cannot do is add
            evidence the record does not have. The verdict you read is the one the published
            sources support.
          </p>
        </div>
      </Section>

      {/* D. The graveyard -- now collapsed: the stat already lives at position 2 of this
          page, so what stood here is a duplicate of the page's thesis, and the "auditable, not
          a black box" line above already says what the kill-log link is for. A single link to
          the log is the only thing missing.

          `bg="white"`: C2 took the `bg` slot above, so D and E each shift one step along to keep
          the page alternating. */}
      <Section
        bg="white"
        width="6xl"
        title="The kill log"
      >
        <div className="max-w-3xl space-y-6">
          {/* This paragraph used to promise publication in full for the whole kill set, 40px above
              a button that then printed 1,364 while the page it opens shows 400. Both are gone: no
              quantity is claimed here, and the button no longer names a count it cannot deliver.
              What is left describes what a published kill CONTAINS, which is what this section is
              for. */}
          <p className="text-body leading-relaxed text-muted">
            Every published kill names the check it failed and the argument that killed it, with
            the sources behind that argument where there were any.
          </p>
          <Link
            href="/kill-log"
            className={buttonClasses({ size: 'lg' })}
          >
            Read the kill log{' '}
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
        bg="bg"
        width="6xl"
        title="The honest limits"
      >
        <div className="max-w-3xl">
          <p className="text-body font-normal leading-relaxed text-muted">
            {`${PACK_DISCLAIMER} ${PACK_SCOPE} No analysis can promise a business outcome.`}
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
