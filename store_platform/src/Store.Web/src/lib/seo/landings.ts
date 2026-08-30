import type { Pack } from '@/lib/api/client';
import type { FacetKind } from '@/lib/facets';
import { VARIANTS, type VariantKey } from '@/lib/copyConfig';

/**
 * Topical landing pages at `/ideas/<slug>`, one per facet value.
 *
 * THE PROBLEM THEY SOLVE. The catalogue is one page with a client-side filter bar. That is a good
 * shopping experience and a poor discovery one: someone searching "business ideas I can run in the
 * evenings" has no URL to land on, because the evenings view exists only as transient state behind
 * a `?commitment=evenings` query a crawler has no reason to guess. Every pack therefore competes
 * for attention only through the home page. These pages give each meaningful slice of the
 * catalogue a stable, linkable, indexable address described in the words a buyer actually uses.
 *
 * WHY THEY ARE NOT DOORWAY PAGES. Google's doorway rule targets sets of near-identical pages that
 * funnel to the same destination and add nothing themselves. The guards against becoming that:
 *
 *  1. Every `intro` below is written once, for that facet, and says something specific and true
 *     about that slice, what the category means and who it suits. None is a template with a noun
 *     swapped in. If you add a landing, write real copy for it; do not paraphrase a neighbour.
 *  2. A landing only renders when the live catalogue holds at least `MIN_PACKS_FOR_LANDING` packs
 *     for it, and 404s otherwise (`pages/ideas/[slug].tsx`). A page listing two packs is thin
 *     content, and thin content is the actual mechanism by which pages like these get demoted.
 *  3. The list is derived from the facet vocabulary the engine already emits, it cannot invent a
 *     category the catalogue does not contain.
 *
 * The threshold makes the set self-regulating: as the daemon publishes, a slice that crosses the
 * bar starts rendering and enters the sitemap; one that never gets there never ships a weak page.
 *
 * THE HONESTY BAR is the same one `lib/facets.ts` sets for its labels: copy may describe WHAT a
 * category is, never assert an outcome the dossiers have not proven. No "profitable", no
 * "high-margin", no earnings figures. On a storefront whose whole position is "every claim
 * sourced", a category page is the last place to make an unsourced claim.
 *
 * `sector: other` ("Specialist niches") deliberately has no landing: a page called "other business
 * ideas" describes nothing and is exactly the thin, purposeless page rule 1 exists to prevent.
 */

/** Below this many matching packs a landing does not render at all. Five is the point at which the
 *  page is a genuine shelf rather than a signpost with a couple of links on it. */
export const MIN_PACKS_FOR_LANDING = 5;

export interface Landing {
  /** URL segment under `/ideas/`. Written the way people search, not the way the code names it. */
  slug: string;
  kind: FacetKind;
  value: string;
  /** The page's visible `<h1>`. */
  h1: string;
  /**
   * The name to use where there is no room for the `h1`: mosaic tiles, chips, breadcrumbs.
   *
   * IT EXISTS SO NOTHING HAS TO TRUNCATE. The old collections tiles cut the `h1` by character
   * budget and rendered "Busin...", which names nothing and reads as a rendering fault.
   * MASTER-BRIEF section 9 bans truncating text by character budget anywhere on the site, and the
   * only way to honour that is to write a short name, not compute one.
   *
   * Nothing is lost: the long name is still the tile's `title` and is still read out to a screen
   * reader. Keep these under about 24 characters and make each one stand on its own. "Evenings"
   * is a category; "Business ideas y" is a bug.
   */
  shortName: string;
  /** `<title>`, minus the site suffix `Seo` appends. */
  metaTitle: string;
  metaDescription: string;
  /** Two or three sentences of real, facet-specific copy. See rule 1 above. */
  intro: string;
}

/*
 * No price in any description. These are `<meta name="description">` strings for 16 static
 * landing pages: no catalogue is fetched to render them, and a search engine keeps the text it
 * crawled for months. They all read "£49 per pack" while the live shelf ran £29 to £199, so the
 * highest-reach surface on the site was also the least correctable one. Price belongs where it
 * can be read from the catalogue (/pricing, the shelf, each pack page).
 */
export const LANDINGS: Landing[] = [
  // ── Who the customer is ──────────────────────────────────────────────────────
  {
    slug: 'b2b-business-ideas',
    kind: 'payer',
    value: 'b2b',
    h1: 'Business ideas that sell to businesses',
    shortName: 'Sells to businesses',
    metaTitle: 'B2B business ideas, researched and sourced',
    metaDescription:
      'Vetted B2B business ideas where the customer is a company with a budget. Each pack names the buyer, the price they pay, and the evidence behind both.',
    intro:
      'These are the packs where the customer is another business. The buyer has a budget line and an approval process, so the sale is a conversation held over weeks. One signed customer can be worth a hundred consumer ones. The payer check, can this customer afford it, is answered against company accounts.',
  },
  {
    slug: 'b2c-business-ideas',
    kind: 'payer',
    value: 'b2c',
    h1: 'Business ideas that sell to consumers',
    shortName: 'Sells to consumers',
    metaTitle: 'B2C business ideas, researched and sourced',
    metaDescription:
      'Vetted consumer business ideas with the buyer, the price and the route to reach them all sourced. One payment per researched pack.',
    intro:
      'Here the person paying is a member of the public, usually at a moment when something has gone wrong or come due. The sale is short and there is no account to manage. The hard part is being findable at the exact moment of need, so the distribution check does most of the work on these packs.',
  },

  // ── Hours it needs from you ──────────────────────────────────────────────────
  {
    slug: 'evening-business-ideas',
    kind: 'commitment',
    value: 'evenings',
    h1: 'Business ideas you can start in the evenings',
    shortName: 'Evenings',
    metaTitle: 'Evening side business ideas that survived a kill-first filter',
    metaDescription:
      'Researched business ideas that fit around a full-time job, evenings and weekends. Each pack cites a source for every claim.',
    intro:
      'Every idea here was assessed as startable outside working hours, without a customer needing you during the day. The constraint is real and it does real work. It rules out anything where the job is answering the phone when the phone rings. What is left is work a customer submits and you turn around on your own schedule.',
  },
  {
    slug: 'part-time-business-ideas',
    kind: 'commitment',
    value: 'part_time',
    h1: 'Part-time business ideas',
    shortName: 'Part time',
    metaTitle: 'Part-time business ideas, researched and sourced',
    metaDescription:
      'Business ideas sized for part-time hours. Every claim cited, one payment per pack.',
    intro:
      'These need more than evenings and less than a full week. It is the middle ground where most businesses get started, usually alongside reduced hours or other work. Each pack says which parts of the week the work has to land in. "Part-time" covers everything from a few scheduled hours to being reachable most days.',
  },

  // ── How much is automated ────────────────────────────────────────────────────
  {
    slug: 'automated-business-ideas',
    kind: 'effort',
    value: 'automatable',
    h1: 'Business ideas where most of the work is automatable',
    shortName: 'Mostly automated',
    metaTitle: 'Automatable business ideas, researched and sourced',
    metaDescription:
      'Business ideas where software does most of the delivery. Each pack sets out what can be automated and what still needs a person.',
    intro:
      'Most of the delivery in these ideas is machine-doable (data gathered, documents produced, checks run). They grow without taking proportionally more of your time. The honest limit is that automatable does not mean autonomous, and each pack names the steps that still need a person.',
  },
  {
    slug: 'part-automated-business-ideas',
    kind: 'effort',
    value: 'part_automatable',
    h1: 'Business ideas that are part automated',
    shortName: 'Part automated',
    metaTitle: 'Part-automated business ideas, researched and sourced',
    metaDescription:
      'Ideas that mix software with judgement. Each pack names which half is which, with sources.',
    intro:
      'A hybrid: software handles the repetitive middle, but the valuable step needs judgement, a decision, a negotiation, a reading of a specific situation. These tend to defend themselves better than fully automated ideas precisely because the part a competitor cannot copy quickly is the part a person does.',
  },

  // ── Skills you already have ──────────────────────────────────────────────────
  {
    slug: 'business-ideas-for-developers',
    kind: 'advantage',
    value: 'code',
    h1: 'Business ideas for people who can build',
    shortName: 'If you can build',
    metaTitle: 'Business ideas for developers and technical founders',
    metaDescription:
      'Researched business ideas where being able to build software is the unfair advantage. Every claim sourced, one payment per pack.',
    intro:
      'These reward being able to build the thing yourself instead of paying someone to. The advantage is speed: you can try five versions of the product in the time it takes a competitor to specify one. The established tooling in these markets is old.',
  },
  {
    slug: 'business-ideas-for-operators',
    kind: 'advantage',
    value: 'ops',
    h1: 'Business ideas for people who are good at operations',
    shortName: 'If you run things well',
    metaTitle: 'Business ideas for people who run things well',
    metaDescription:
      'Researched business ideas where running a tight process is the advantage. Every claim sourced, one payment per pack.',
    intro:
      'The advantage here is process: turning something chaotic into something that reliably happens on time, at a predictable cost. These ideas sit in markets where simple work is done badly and inconsistently by everyone currently doing it. The gap that leaves is what someone who runs things well walks into.',
  },
  {
    slug: 'business-ideas-for-salespeople',
    kind: 'advantage',
    value: 'sales',
    h1: 'Business ideas for people who can sell',
    shortName: 'If you can sell',
    metaTitle: 'Business ideas for salespeople and closers',
    metaDescription:
      'Researched business ideas where the bottleneck is distribution, not building. Every claim sourced, one payment per pack.',
    intro:
      'In these, the hard part is getting in front of the buyer and closing. They suit someone comfortable with outbound conversation and rejection. Without that, the pack stalls no matter how good the product gets.',
  },

  // ── How it makes money ───────────────────────────────────────────────────────
  {
    slug: 'productised-service-ideas',
    kind: 'mechanism',
    value: 'productized_service',
    h1: 'Fixed-price service ideas',
    shortName: 'Fixed-price work',
    metaTitle: 'Fixed-price service business ideas, researched and sourced',
    metaDescription:
      'Fixed scope, fixed price, repeatable delivery. Researched fixed-price service ideas at one payment per pack.',
    intro:
      'A fixed-price service sells a defined outcome at a fixed price instead of billing for hours: the same job done the same way, over and over. This is the shortest path to a first paying customer. You can sell it before you have built any of the machinery that later makes it efficient.',
  },
  {
    slug: 'vertical-software-ideas',
    kind: 'mechanism',
    value: 'vertical_tool',
    h1: 'Software for one trade',
    shortName: 'Software for one job',
    metaTitle: 'Software business ideas aimed at one trade',
    metaDescription:
      'Software ideas aimed at one trade or profession. Every claim cited, one payment per researched pack.',
    intro:
      'Software built for one trade or profession. The bet is depth over reach: a tool that knows the forms, rules and vocabulary of a single industry is hard for a general-purpose competitor to match. The buyer is easy to find, because they all read the same few places.',
  },
  {
    slug: 'marketplace-and-broker-ideas',
    kind: 'mechanism',
    value: 'transaction_broker',
    h1: 'Ideas that connect two sides of a deal',
    shortName: 'Connecting two sides',
    metaTitle: 'Business ideas that connect two sides of a deal',
    metaDescription:
      'Ideas that earn by connecting two sides of a deal. One payment per researched pack, and each one says how you get the first people on both sides.',
    intro:
      'These earn a cut for standing between two parties who struggle to find each other. You carry no inventory and little delivery cost. The difficulty is getting the first people on both sides, because neither side turns up for an empty market. Each pack says which side it gets first, and how.',
  },

  // ── Sector ───────────────────────────────────────────────────────────────────
  {
    slug: 'red-tape-and-licensing-ideas',
    kind: 'sector',
    value: 'licensing_admin',
    h1: 'Business ideas in licensing and red tape',
    shortName: 'Licensing and red tape',
    metaTitle: 'Licensing, permits and compliance business ideas',
    metaDescription:
      'Researched business ideas built on permits, licences and mandatory admin, deadlines someone has to meet. One payment per pack.',
    intro:
      'Licences, permits and the paperwork that is not optional. The deadline is set by someone other than the customer, which is what makes this sector durable. The work recurs whether or not anyone feels like doing it. People are paying to avoid the cost of getting it wrong.',
  },
  {
    slug: 'pay-and-worker-rights-ideas',
    kind: 'sector',
    value: 'employment_pay',
    h1: 'Business ideas in pay and worker rights',
    shortName: 'Pay and worker rights',
    metaTitle: 'Employment, pay and worker rights business ideas',
    metaDescription:
      'Researched business ideas around wages, entitlements and employment admin, with the legality check applied. One payment per pack.',
    intro:
      'Wages, entitlements and the disputes that follow when they are wrong. This sector carries real regulatory weight, so the legality check does more work here than anywhere else. Ideas in this space have been killed outright at that gate, and the kill log records why.',
  },
  {
    slug: 'care-and-benefits-ideas',
    kind: 'sector',
    value: 'care_benefits',
    h1: 'Business ideas in care and benefits',
    shortName: 'Care and benefits',
    metaTitle: 'Care and benefits claim business ideas, researched',
    metaDescription:
      'Researched business ideas around care arrangements and benefits entitlement, each with a sourced payer and legality check. One payment per pack.',
    intro:
      'Care arrangements, entitlements and the claims process around them. These reach people at a genuinely difficult moment, which raises the bar. The payer check has to establish who pays when the person who needs the help cannot. The legality check has to be satisfied before anything reaches the catalogue.',
  },
  {
    slug: 'trades-and-construction-ideas',
    kind: 'sector',
    value: 'trades_construction',
    h1: 'Business ideas in trades and site work',
    shortName: 'Trades and site work',
    metaTitle: 'Trades and construction business ideas, researched',
    metaDescription:
      'Researched business ideas serving builders, trades and site operations. Every claim sourced, one payment per pack.',
    intro:
      'Serving the people who do physical work on sites and in homes. These customers are underserved by software because they are not at a desk. They pay quickly for anything that removes an evening of paperwork, and abandon anything that assumes they have a desk.',
  },
];

/** Map for slug lookup. Slugs are unique by construction; the test suite holds that. */
const BY_SLUG = new Map(LANDINGS.map((landing) => [landing.slug, landing]));

export function landingBySlug(slug: string | undefined): Landing | undefined {
  return slug ? BY_SLUG.get(slug) : undefined;
}

/**
 * Does this pack belong on this landing?
 *
 * `advantage` is the multi-valued facet (a pack carries up to three), so it is a membership test;
 * every other kind holds a single value and is an equality test. A pack whose facet the engine
 * could not justify carries `null` and matches nothing, it appears under the unfiltered
 * catalogue only, which is the same rule the filter bar applies.
 */
export function packMatchesLanding(pack: Pack, landing: Landing): boolean {
  if (landing.kind === 'advantage') {
    return (pack.advantages ?? []).includes(landing.value as never);
  }
  return pack[landing.kind] === landing.value;
}

/** The landings the live catalogue can actually fill, in declaration order. Used by the sitemap and
 *  by the cross-links on the catalogue, so both agree with what `/ideas/<slug>` will really serve. */
export function eligibleLandings(packs: Pack[]): { landing: Landing; count: number }[] {
  return LANDINGS.map((landing) => ({
    landing,
    count: packs.filter((pack) => packMatchesLanding(pack, landing)).length,
  })).filter(({ count }) => count >= MIN_PACKS_FOR_LANDING);
}

/**
 * Category landing-page `<h1>` for a given slug and copy variant.
 * Falls back to the static landing definition, and finally to the slug itself.
 */
export function landingH1(slug: string, variant: VariantKey): string {
  return VARIANTS[variant].categoryH1[slug] ?? landingBySlug(slug)?.h1 ?? slug;
}

/**
 * Category landing-page `<title>` (minus the site suffix) for a given slug and copy variant.
 */
export function landingMetaTitle(slug: string, variant: VariantKey): string {
  return VARIANTS[variant].categoryMetaTitle[slug] ?? landingBySlug(slug)?.metaTitle ?? '';
}
