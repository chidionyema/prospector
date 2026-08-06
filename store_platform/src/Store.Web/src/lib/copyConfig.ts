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
  'business-ideas-for-operators': 'Business ideas for operators',
  'business-ideas-for-salespeople': 'Business ideas for salespeople',
  'productised-service-ideas': 'Productised service ideas',
  'vertical-software-ideas': 'Vertical‑software business ideas',
  'marketplace-and-broker-ideas': 'Marketplace and broker business ideas',
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

const CATEGORY_H1_C: Record<string, string> = {
  ...CATEGORY_H1_A,
  'automated-business-ideas': 'High-leverage operations',
  'b2b-business-ideas': 'B2B markets',
  'b2c-business-ideas': 'B2C markets',
  'evening-business-ideas': 'Asynchronous operations',
  'part-time-business-ideas': 'Fractional capacity models',
  'business-ideas-for-developers': 'Technical execution models',
  'business-ideas-for-operators': 'Operational execution models',
  'business-ideas-for-salespeople': 'Go‑to‑market execution models',
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
    globalHookLead: 'Business ideas with the research already done.',
    // CUT from 175 characters to ~80 (2026-08-06). At 390px the long version wrapped to four
    // lines and cost 200px of the first screen on its own, which was the single largest reason a
    // phone's opening screen contained no product at all. What it listed -- buyer, price, unit
    // economics, go-to-market -- is the pack's contents page, and the pack's contents page belongs
    // in "What you get", not in the subhead. The subhead's job is one sentence of what this is.
    globalHookDescription:
      'The buyer, the price, the margins and the plan. Every claim links to its source.',

    howItWorksEyebrow: 'The panel',
    howItWorksTitle: 'Every idea faces a panel built to kill it.',
    howItWorksLead:
      'Before anything reaches the store, it runs a gauntlet of AI agents that each hunt for the reason it fails. Here is exactly how an idea earns its place.',
    howItWorksSeoDescription:
      'How Mumchimp works: every pack is a grounded business opportunity, vetted against a filter built to kill it and sourced to retrievable evidence before it can be listed.',

    sixChecksTitle: 'The checks, one kill, and it stops',
    sixChecksDescription:
      'Every candidate faces the same filter, in this order. The panel kills fast at the first hard fail. Which checks run depends on the idea, and the pack page names the ones it faced. Only ideas that clear every hard gate and survive an adversarial cross‑examination become a pack, and every kill is logged with its reason, so the filter is auditable, not a black box.',

    automatedIdeasIntro:
      'Code does the heavy lifting. These ideas scale on software, not your time. The core delivery (gathering data, generating docs, running checks) is automated rather than billed by the hour. We will tell you exactly where you still need a human in the loop.',

    categoryH1: CATEGORY_H1_A,
    categoryMetaTitle: CATEGORY_H1_A, // mirror for now
  },

  b: {
    globalHookLead: 'Business ideas with the economics already verified.',
    globalHookDescription:
      'The buyer, the price, the unit economics and the plan. Every number links to its source.',

    howItWorksEyebrow: 'The panel',
    howItWorksTitle: 'Every idea is tested to destruction.',
    howItWorksLead:
      'Before an idea reaches the store, it faces a panel of AI agents designed to figure out why it would fail. They hunt for hidden legal red tape, a lack of real demand, and bad profit margins. If it survives, it gets published. If it fails, we document exactly why.',
    howItWorksSeoDescription:
      'How Mumchimp works: every idea is tested to destruction by a panel of AI agents before it can be listed.',

    sixChecksTitle: 'The checks every pack faced',
    sixChecksDescription:
      'Every pack faced the same filter: a real problem, proven value, room to compete, buyers who can pay, a clear way to reach them, and no legal red tape. Which checks ran depends on the idea, and the pack page shows exactly which ones it cleared.',

    automatedIdeasIntro:
      'Businesses where systems do the heavy lifting. Delivery relies on tools, templates, and automated checks so you do not run out of hours as you grow. We are honest about the limits: automatable does not mean autonomous. We list the exact steps that still require your input.',

    categoryH1: CATEGORY_H1_B,
    categoryMetaTitle: CATEGORY_H1_B,
  },

  c: {
    globalHookLead: 'Business ideas with a source behind every number.',
    globalHookDescription:
      'The buyer, the price, the margins and the plan. Every number links to the page it came from.',

    howItWorksEyebrow: 'The methodology',
    howItWorksTitle: 'An adversarial review process.',
    howItWorksLead:
      'Before publication, every concept is subjected to a simulated panel of AI agents programmed to invalidate the business model. They assess regulatory friction, market saturation, and margin compression. Validated models are published; failed models are documented in the Kill Log.',
    howItWorksSeoDescription:
      'How Mumchimp works: every dossier is subjected to an adversarial review by AI agents before it can be listed.',

    sixChecksTitle: 'The rigid criteria',
    sixChecksDescription:
      'Every dossier is held to the same rigid criteria: verified market pain, quantifiable value, fragmented incumbents, a solvent payer base, viable acquisition channels, and regulatory compliance. The criteria applied depend on the model under review, and each dossier records which were run.',

    automatedIdeasIntro:
      'High-leverage operations. The core unit of delivery in these models is machine-executable: data parsing, document generation, and compliance checks. This decouples revenue from billable hours. Each dossier explicitly outlines the operational bottlenecks that still require human oversight.',

    categoryH1: CATEGORY_H1_C,
    categoryMetaTitle: CATEGORY_H1_C,
  },
};
