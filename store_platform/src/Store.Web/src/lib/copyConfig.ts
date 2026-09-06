/**
 * Centralised A/B/C copy dictionary.
 *
 * OWNER: the founder. Every string below is the founder's copy, no AI generation,
 * no runtime modification. Changing a string here changes what a variant's buyer sees.
 *
 * VARIANT KEYS
 *   'a': The Indie Builder  (technical, fast execution)
 *   'b': The Domain Expert  (non-technical, reliable systems)
 *   'c': The Data Skeptic   (analytical, risk-averse, needs proof)
 *
 * SLOTS
 *   Each slot maps to one place in the UI. The consumer (`pages/*`, `lib/seo/*`) reads
 *   `variant[slot]` and renders the string. The dictionary owns the text; the consumer
 *   owns the markup.
 *
 * ADDING A SLOT
 *   1. Add the key to the `CopySlots` interface below.
 *   2. Add the three variant strings to the `VARIANTS` map.
 *   3. Read `variant.<key>` in the consuming component.
 *   4. Add a contract-test assertion that the key exists in all three variants.
 */

export type VariantKey = 'a' | 'b' | 'c';

/** Every copy slot consumed by the storefront. */
export interface CopySlots {
  /** Hero lead paragraph on `/` (`pages/index.tsx`). */
  globalHookLead: string;
  /** Hero description under the lead on `/`. */
  globalHookDescription: string;

  /** How-it-works hero eyebrow (`/how-it-works`). */
  howItWorksEyebrow: string;
  /** How-it-works hero title. */
  howItWorksTitle: string;
  /** How-it-works hero lead. */
  howItWorksLead: string;
  /** How-it-works SEO description. */
  howItWorksSeoDescription: string;

  /** Six-checks section title (`/how-it-works` methodology section). */
  sixChecksTitle: string;
  /** Six-checks section description. */
  sixChecksDescription: string;

  /** `/ideas/automated-business-ideas`, the landing-page intro. */
  automatedIdeasIntro: string;

  /** Category landing-page `<h1>` (keyed by slug). */
  categoryH1: Record<string, string>;
  /** Category landing-page `<meta name="description">` (keyed by slug). */
  categoryMetaTitle: Record<string, string>;
}

export type CopyVariant = CopySlots;

const CATEGORY_H1_A: Record<string, string> = {
  'automated-business-ideas': 'Business ideas where most of the work is automatable',
  'b2b-business-ideas': 'Business ideas that sell to businesses',
  'b2c-business-ideas': 'Business ideas that sell to consumers',
  'evening-business-ideas': 'Business ideas you can start in the evenings',
  'part-time-business-ideas': 'Part-time business ideas',
  'part-automated-business-ideas': 'Part‑automated business ideas',
  'business-ideas-for-developers': 'Business ideas for developers',
  'business-ideas-for-operators': 'Business ideas for people who run things well',
  'business-ideas-for-salespeople': 'Business ideas for salespeople',
  'productised-service-ideas': 'Fixed-price service ideas',
  'vertical-software-ideas': 'Software ideas for one trade',
  'marketplace-and-broker-ideas': 'Business ideas connecting two sides of a deal',
  'red-tape-and-licensing-ideas': 'Red‑tape and licensing business ideas',
  'pay-and-worker-rights-ideas': 'Pay and worker‑rights business ideas',
  'care-and-benefits-ideas': 'Care and benefits business ideas',
  'trades-and-construction-ideas': 'Trades and construction business ideas',
};

const CATEGORY_H1_B: Record<string, string> = {
  ...CATEGORY_H1_A,
  'automated-business-ideas': 'Businesses where systems do the heavy lifting',
  'b2b-business-ideas': 'Selling to businesses',
  'b2c-business-ideas': 'Selling to consumers',
  'evening-business-ideas': 'Evenings and weekends',
  'part-time-business-ideas': 'Part-time ventures',
  'business-ideas-for-developers': 'For people who can build',
  'business-ideas-for-operators': 'For people who can operate',
  'business-ideas-for-salespeople': 'For people who can sell',
};

// DE-JARGONED 2026-08-13, same reason as the C prose block below. These are page headings a
// stranger arrives on from a search result: "Fractional capacity models" and "Asynchronous
// operations" are our filing system, not their words, and a heading nobody recognises is a
// bounce. C stays the precise, evidence-first variant; precise is not the same as Latinate.
const CATEGORY_H1_C: Record<string, string> = {
  ...CATEGORY_H1_A,
  'automated-business-ideas': 'Businesses that grow without more of your hours',
  'b2b-business-ideas': 'Businesses whose customers are businesses',
  'b2c-business-ideas': 'Businesses whose customers are people',
  'evening-business-ideas': 'Businesses you can run around a job',
  'part-time-business-ideas': 'Businesses that fit the hours you have',
  'business-ideas-for-developers': 'Businesses built on code you write',
  'business-ideas-for-operators': 'Businesses built on running things well',
  'business-ideas-for-salespeople': 'Businesses built on selling',
};

/** Every variant, every slot, one source of truth. */
export const VARIANTS: Record<VariantKey, CopyVariant> = {
  a: {
    // ONE claim. This read "Skip 6 months of research. Validated ideas you can actually ship
    // today. Zero fluff, ready to build. £49 a pack." -- four assertions racing each other, and a
    // headline making four claims makes none: the eye picks whichever one it happens to land on.
    // The price left the h1 because it is already in the eyebrow directly above it and in the lead
    // paragraph directly below; it was stated three times within 120px. Each variant now tests one
    // distinct promise (research done / economics verified / every number sourced) rather than
    // three overlapping paragraphs, which is also the only shape an A/B result can be read from.
    // Homepage h1, variant a. The live line since 2026-08-18. Variant b is the stronger
    // "Skip 6 months of research. Launch a business or side hustle.", the live h1 from 05e47bc9 (2026-07-29).
    // New visitors are split 50/50 in `pickVisitorVariant`; crawlers stay on a.
    // Founder, 2026-09-03: the July line is the strong headline. It is the default.
    globalHookLead: 'Skip 6 months of research. Launch a business or side hustle.',
    // CUT from 175 characters to ~80 (2026-08-06). At 390px the long version wrapped to four
    // lines and cost 200px of the first screen on its own, which was the single largest reason a
    // phone's opening screen contained no product at all. What it listed -- buyer, price, unit
    // economics, go-to-market -- is the pack's contents page, and the pack's contents page belongs
    // in "What you get", not in the subhead. The subhead's job is one sentence of what this is.
    // THE MECHANISM MOVED INTO THE SUBHEAD (2026-08-13, 33-F). AI was disclosed on three
    // surfaces and every one of them was defensive: a warranty exclusion in the terms, a
    // liability line in the footer, and a correction of an assumption on /how-it-works. A fact
    // that appears only where a company manages its risk reads as a fact it wishes were
    // otherwise, which is exactly how the founder read it. It is not a volume problem, so the
    // fix is not a fourth mention: it is one clause, in the sentence that already says what
    // this is, written as a reason to buy. No new line, because the 175-to-80 cut above was
    // measured against the fold and a third paragraph would spend that back.
    globalHookDescription:
      'The buyer, the price and the plan, checked against sourced evidence before it goes on sale.',

    howItWorksEyebrow: 'The research',
    howItWorksTitle: 'Every idea is stress-tested before it can go on sale.',
    howItWorksLead:
      'We run market gaps through our AI research engine to stress-test the buyer, the price, and the plan. Only the top 6% survive the checks.',
    howItWorksSeoDescription:
      'How Mumchimp works: every pack is a sourced business idea, stress-tested against cited evidence before it goes on sale.',

    // NOT "Six checks, in order." The bare cardinal is the same closed-set promise corrected in
    // variant b below, and it survived because `fixedCheckCount.test.ts` only banned a numeral
    // sitting behind a DETERMINER ("all six checks", "the six gates"). "Six checks" needs no
    // determiner to make the claim, and a section title is the strongest place to make it.
    //
    // It also contradicted the section directly above it. /how-it-works renders the worked
    // evidence record first (`CheckSequence`, reading `data/sample-report.json`) and that record
    // runs NINE checks -- six supported, two unverifiable, one refuted. So the page showed a
    // reader nine checks and then titled the next section "Six checks, in order", which is the
    // one kind of contradiction a page arguing for auditability cannot afford. The list below
    // this heading is six long because `COMMON_CHECKS` is the set common to EVERY lane, not the
    // set any particular pack ran; 23 of the 63 packs measured on 2026-08-06 report a denominator
    // other than six.
    //
    // Dropping the numeral costs nothing the heading was doing: the list is still ordered, still
    // six long, and the description still says some ideas face more. What goes is the promise
    // that six is all there is.
    sixChecksTitle: 'The checks, in order. One hard fail and it stops.',
    sixChecksDescription:
      'Some ideas face more checks, and each pack page names its own. Every rejection is logged with the reason that fired it, so you can audit the filter yourself.',

    automatedIdeasIntro:
      'Code does the heavy lifting. These ideas scale on software instead of your hours. The core delivery (gathering data, generating documents, running checks) is automated. We will tell you exactly where you still need a person.',

    categoryH1: CATEGORY_H1_A,
    categoryMetaTitle: CATEGORY_H1_A, // mirror for now
  },

  b: {
    globalHookLead: 'Business opportunities with the research already done.',
    globalHookDescription:
      'The buyer, the numbers and the plan, checked by an AI paid to find the flaw.',

    howItWorksEyebrow: 'The research',
    howItWorksTitle: 'Every idea is checked against cited evidence first.',
    howItWorksLead:
      'Before a pack reaches the catalogue, the research engine hunts for hidden red tape, a buyer who cannot pay, and a price that will not hold. What passes is published. What fails is logged with the check that killed it.',
    howItWorksSeoDescription:
      'How Mumchimp works: every idea is stress-tested against cited evidence before it can be listed.',

    // NOT "The checks every pack faced". It sat above a list of exactly six steps, which made
    // the heading assert that the six ARE the set -- the same falsehood corrected in about.tsx
    // and faqContent.ts on 2026-08-06, surviving here because the guard that caught those reads
    // only about.tsx. 23 of the 63 live packs report a denominator other than 6.
    sixChecksTitle: 'The checks an idea has to pass',
    sixChecksDescription:
      'Every pack faced the same bar: a real problem, proven value and room to compete. Then buyers who can pay, a clear way to reach them and no legal red tape. The checks that ran depend on the idea, and the pack page shows the ones it cleared.',

    automatedIdeasIntro:
      'Businesses where systems do the heavy lifting. Delivery relies on tools, templates, and automated checks so you do not run out of hours as you grow. We are honest about the limits: automatable does not mean autonomous. We list the exact steps that still require your input.',

    categoryH1: CATEGORY_H1_B,
    categoryMetaTitle: CATEGORY_H1_B,
  },

  c: {
    globalHookLead: 'Business opportunities with a source behind every number.',
    globalHookDescription:
      'The buyer, the price and the plan. An AI checked every number against a page you can open.',

    // VARIANT C DE-JARGONED (2026-08-13). C is the proof-hungry reader, and its copy had been
    // reading that as Latinate abstraction: "regulatory friction", "margin compression",
    // "fragmented incumbents", "high-leverage operations", "the core unit of delivery is
    // machine-executable". Precision is not the same thing as vocabulary. B carried the SAME
    // content in words a reader already owns ("a real problem, proven value, room to compete,
    // buyers who can pay, a clear way to reach them, and no legal red tape"), which is the proof
    // that the register was a choice and not a limit of the material. C keeps its distinct
    // promise, evidence first, and now states it in English.
    howItWorksEyebrow: 'The methodology',
    howItWorksTitle: 'We try to prove every idea wrong first.',
    howItWorksLead:
      'The research engine looks for a legal block, a buyer who cannot pay, or a market already taken. What passes is published with its sources. What fails is published on /rejected, with the evidence.',
    howItWorksSeoDescription:
      'How Mumchimp works: each idea is stress-tested against cited evidence, and the ideas that fail are published too, with the evidence.',

    sixChecksTitle: 'The same bar, every time',
    sixChecksDescription:
      'Every pack clears the same bar: a real problem, value that lasts and room to compete. Then buyers with money to spend, a way to reach them and nothing illegal about it. The checks that ran depend on the idea, and each pack page lists the ones it cleared.',

    automatedIdeasIntro:
      'Businesses where software does the work. Reading data, producing documents, running checks: that is the part that scales, and it is why the income stops tracking the hours you put in. Each pack is explicit about the steps that still need you.',

    categoryH1: CATEGORY_H1_C,
    categoryMetaTitle: CATEGORY_H1_C,
  },
};
