import React from 'react';
import type { GetStaticProps } from 'next';
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
import AttritionCascade from '@/components/marketing/AttritionCascade';
import { buildKillIndex, type GateBar } from '@/lib/killLog.server';
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
  const match = entries.find((e) => e.title.toLowerCase().includes(titleFragment.toLowerCase()));
  if (match) return match;
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

/**
 * The cascade's counts, read once at build time from the same place the kill log reads them.
 *
 * `buildKillIndex` is imported by a `getStaticProps` and nothing else on this page, so Next drops
 * it from the client bundle along with the 400-entry JSON behind it. The alternative was a second
 * table of gate counts typed into this file, which is the defect the shared data layer exists to
 * stop: three pages once stated three different pack totals because each counted for itself.
 */
export const getStaticProps: GetStaticProps<{ distribution: GateBar[] }> = async () => ({
  props: { distribution: buildKillIndex().distribution },
});

export default function HowItWorks({ distribution }: { distribution: GateBar[] }) {
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
            <p className="mt-2 lede">
              {RESEARCH_STATS.rejectRateLabel} died on cited evidence. {killsSummary()}.
            </p>
          </div>
          <FunnelDiagram className="w-full md:w-[340px]" />
        </div>

        {/* THE FACTS ROW (`mockups/how-it-works.html`, `.facts`). Three figures, one border, three
            equal cells. It reads the same `RESEARCH_STATS` the paragraph above reads, so the two
            cannot disagree.

            It is the drawing's `.facts` block now (`mockups/how-it-works.html:76-82`): three
            equal cells in one card, `.facts span` for the label and `.facts b` for the figure. The
            grid, border and padding utilities that used to hold those numbers are removed rather
            than layered, since mumchimp.css is imported into `layer(components)` (globals.css:8) and
            a utility left in place would beat the class.
            The label case comes from `.facts span` in the drawing's own stylesheet, not from our
            markup. `weightAndCasePolicy` and `monoIsTheDataVoice` read OUR source, so they neither
            catch this nor need to: the rule they exist to stop is us hand-writing `uppercase` and
            `tracking-*` on prose, and the figures keep the mono face a figure is for. */}
        <dl className="facts">
          <div>
            <dt><span>Ideas in</span></dt>
            <dd><b className="num">{RESEARCH_STATS.researched.toLocaleString('en-GB')}</b></dd>
          </div>
          <div>
            <dt><span>Killed on cited evidence</span></dt>
            <dd><b className="num">{RESEARCH_STATS.killed.toLocaleString('en-GB')}</b></dd>
          </div>
          <div>
            <dt><span>Died at a gate</span></dt>
            <dd><b className="num">{RESEARCH_STATS.rejectRateLabel}</b></dd>
          </div>
        </dl>
      </Section>

      {/*
       * THE ATTRITION CASCADE (MASTER-BRIEF section 7), and it is the signature of this page.
       *
       * Everything else here describes what the checks ARE. This is the only thing that shows what
       * they DID. A reader who watches the bar lose most of its width at one gate has understood
       * that the filter is real in a way six paragraphs about six checks cannot achieve.
       *
       * Its own section, not beside the funnel, because the section above is held to one diagram
       * by the density rule and the funnel is that diagram. The two say different things: the
       * funnel is the shape of the process, the cascade is the count at every step of it.
       */}
      <Section bg="surface" outerClassName="!border-b-0">
        <h2 className="sec">Where the ideas went</h2>
        <p className="mt-3 lede">
          Every check that killed something, in the order of how much it killed, with the number
          taken off the total each time.
        </p>
        <AttritionCascade distribution={distribution} className="mt-8" />
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
        rule
        intro="Every pack in the catalogue carries an evidence record like this. The one below is real, it is the free sample, and every source in it opens."
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
        rule
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
        <p className="mb-10 lede">
          AI agents run the checks below. Each may only rule on passages it fetched from the open
          web, and those sources are published with the verdict, so you can hold the reasoning
          against them yourself. A person reads that record before a pack goes on sale.
        </p>
        {/* THE DRAWING'S CHECK CARD (`mockups/how-it-works.html`, `.card.incard` of `.checkrow`).

            It was a stepped timeline: a 40px numbered badge per check with a 2px rail drawn
            between the badges, and the example in a nested card inside each step. That is a
            different object from the drawing, which puts all six checks in ONE bordered card as
            hairline-separated rows -- a mono numeral at 32px, the check, the example under it, and
            "See kills" on the right of the row. The timeline read as six stacked cards, so the
            page said "six separate things" where the drawing says "one list, read it down".

            Every utility that set what `.checkrow` sets is gone rather than layered over it:
            `mumchimp.css` is imported into `layer(components)` (globals.css:8), so a utility on the
            same element wins and the class would draw nothing. */}
        <div className="card incard">
          {COMMON_CHECKS.map((check, i) => {
            const example = findExample(check, EXAMPLE_TITLES[check.id] ?? '');
            /* The count comes from the same build-time index the cascade above uses, matched on
               the check's own id AND its aliases -- the engine writes several gate ids per check,
               and matching on `check.id` alone silently reported zero for the two that are only
               ever written under an alias. */
            const died = distribution
              .filter((bar) => idsFor(check).includes(bar.gate))
              .reduce((total, bar) => total + bar.count, 0);
            return (
              <div key={check.id} className="checkrow">
                <span className="i num">{String(i + 1).padStart(2, '0')}</span>
                <div>
                  <h3>{check.name}</h3>
                  {example ? (
                    <p>
                      <strong className="font-semibold text-text">{example.title}</strong>
                      {' '}&middot; {firstSentences(plainEnglish(example.reason), 160)}
                    </p>
                  ) : (
                    /* No example in the log for this gate is not worth a sentence apologising for
                       itself. The check's own refutation says what the gate looks for, which is
                       what the row is for. */
                    <p>{check.refutation}</p>
                  )}
                  <p className="srcs">
                    {died > 0 && (
                      <>
                        <b className="text-kill">{died}</b> ideas died here
                        {example ? ' \u00b7 ' : ''}
                      </>
                    )}
                    {example && <>killed by &ldquo;{example.gateLabel}&rdquo;</>}
                  </p>
                </div>
                {/* `.tlink.go`: the drawing's row action. `.go` carries no desktop rule of its own
                    -- it exists so the mobile breakpoint can move the action out of the third
                    column and under the body (`.checkrow .v,.checkrow .go{grid-column:2}`). */}
                <Link href="/kill-log" prefetch={false} className="tlink go">
                  See kills
                </Link>
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
        rule
      >
        <div className="max-w-3xl space-y-4">
          <p className="font-normal lede">
            They hunt for contradictions, weak citations, and gaps the first pass missed. The
            evidence record survives only if every objection is answered by evidence already on file.
            No new research, no hand-waving.
          </p>
          {/* THE EVIDENCE DEVICE (`mockups/how-it-works.html`, `.evidence`): a teal left edge and
              tint behind the one sentence on this page that a reader is most likely to have got
              backwards, with the count under it in mono. It was a third paragraph in a stack of
              three, which is exactly how a load-bearing sentence gets skimmed. */}
          <div className="evidence">
            <p>
              Silence in the record means <strong className="font-semibold">unverifiable</strong>,
              never <strong className="font-semibold">false</strong>. The agents only rule on pages
              they actually fetched.
            </p>
          </div>
          {/* MASTER-BRIEF §5.3. "Pushed back" is on the homepage hero, on the check list under it,
              on /sample and on every pack page, and until now no page said what it meant. A reader
              met a third verdict word beside "survived" and "killed" and had to guess whether it
              was a soft failure. It is not. This is the page that explains the process, and this
              paragraph is where the same idea already lives, so the definition goes here rather
              than in a fourth place. */}
          <p className="lede">
            A check that is <em>pushed back</em> means the check found nothing decisive either
            way. The idea continued, and the doubt stays on the record where you can read it. It is
            drawn in amber, never red. Red means killed.
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
        rule
      >
        <div className="max-w-3xl space-y-4">
          <p className="font-normal lede">
            Automating the finding, the checking and the sourcing is what lets every idea get the
            same treatment, instead of the handful a person could read. But nothing goes on sale
            on its own: a person reads the verdict, opens the sources, and checks the
            argument holds before a pack is published.
          </p>
          <p className="lede">
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
        rule
      >
        <div className="max-w-3xl space-y-6">
          {/* This paragraph used to promise publication in full for the whole kill set, 40px above
              a button that then printed 1,364 while the page it opens shows 400. Both are gone: no
              quantity is claimed here, and the button no longer names a count it cannot deliver.
              What is left describes what a published kill CONTAINS, which is what this section is
              for. */}
          <p className="lede">
            Every published kill names the check it failed and the argument that killed it, with
            the sources behind that argument where there were any.
          </p>
          <Link
            href="/kill-log" prefetch={false}
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
        rule
      >
        <div className="max-w-3xl">
          <p className="font-normal lede">
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
