/**
 * Every external number this storefront prints, with the page it came from.
 *
 * This exists because of a specific thing that shipped. `ComparisonBlock` carried the line
 * "Typically $300 to $1,000 a year", and the comment above it said, in writing:
 *
 *   > The "$300 to $1,000 a year" range is the figure this page already carried before this
 *   > rewrite, it is unsourced, so it is hedged as "typically".
 *
 * A hedge is not a source. `CLAUDE.md` opens with "every factual claim and quantitative figure
 * must cite a retrievable source or be marked `unverifiable`. No unsourced numbers ship, ever",
 * and the page breaking that rule is the page that sells it. We reject other people's ideas for
 * exactly this, with a kill log to prove it, and then asked strangers to trust an invented range.
 *
 * So the fix is not a better hedge, it is the same rule applied to us. A figure lives here with
 * the publisher, the URL, and the date we read it, or it does not appear on the site. There is
 * no field for a number whose origin we cannot name.
 *
 * `sources.test.ts` enforces both halves: every entry is complete, and no bare currency figure
 * may reappear in the marketing copy without coming through here.
 *
 * On what is deliberately NOT in this file: IdeaBrowser publishes plan prices that a comparison
 * would have liked, and its pricing page returned HTTP 429 on 2026-08-01 for every attempt. It
 * is therefore not cited. Second-hand prices from affiliate review blogs were available and were
 * not used, a figure sourced to a page that is itself selling the referral is the failure this
 * registry exists to prevent, not a fallback when the primary is down.
 */

export interface CitedFigure {
  /** Stable key used by `SourcedFigure`; never rendered. */
  id: string;
  /** The figure as the source prints it. Not converted, not rounded, not averaged with anything. */
  figure: string;
  /** What the source says the figure is the price OF, in the source's own terms. */
  of: string;
  /** Who published it. Rendered, because an anonymous number is the thing being fixed. */
  publisher: string;
  /** The page the figure is on. Must be the primary source: the seller's own page, or the
   *  publisher's own price list, never a review site quoting one. */
  url: string;
  /** ISO date we last read the page ourselves. Rendered, because a price is perishable. */
  checkedOn: string;
  /** Publication or last-updated date printed BY the source, when it prints one. */
  publishedOn?: string;
  /** Anything a reader needs in order to not over-read the figure. Rendered wherever there is
   *  room for it. This is where a comparison is allowed to argue against itself. */
  caveat?: string;
}

export const CITED_FIGURES: readonly CitedFigure[] = [
  {
    id: 'idea-feed-entry-plan',
    figure: '$39/month',
    of: 'the entry "Entrepreneur" plan of a trend-discovery subscription',
    publisher: 'Exploding Topics',
    url: 'https://explodingtopics.com/pricing',
    checkedOn: '2026-08-01',
    caveat:
      'One product’s published price. It is not a survey of the category, and their other plans are listed at $99 and $249 a month.',
  },
  {
    id: 'documentary-research',
    figure: '€4,000 minimum, €6,000 average',
    of: '“Documentary research”, their term for desk research through published sources',
    publisher: 'IntoTheMinds',
    url: 'https://www.intotheminds.com/blog/en/market-research-what-does-it-cost/',
    checkedOn: '2026-08-01',
    publishedOn: '2025-02-26',
    caveat:
      'Their price list, for a question a client brings them. A pack answers a question we chose and already ran, which is why it can cost what it costs. The comparison is one of method.',
  },
];

const BY_ID = new Map(CITED_FIGURES.map((figure) => [figure.id, figure]));

/**
 * Look up a figure, throwing on an unknown id.
 *
 * It throws rather than returning undefined so that a typo fails the build and the test run
 * instead of rendering an empty span where a price used to be. A silently missing number is the
 * one failure mode worse than an unsourced one.
 */
export function citedFigure(id: string): CitedFigure {
  const found = BY_ID.get(id);
  if (!found) throw new Error(`Unknown cited figure: ${id}`);
  return found;
}
