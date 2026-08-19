import { BRAND, LEGAL, SITE_URL } from '@/lib/config';
import { DEFAULT_OG_IMAGE_PATH } from './ogImage';

/**
 * schema.org node builders, shared by every page.
 *
 * WHY A SHARED MODULE. Before this, structured data lived in two places that could not refer to
 * each other: a site-wide Organization + WebSite graph hardcoded in `_document.tsx`, and a
 * standalone Product blob in `productJsonLd.ts`. Because the Product carried no `@id` reference
 * back to the Organization, a crawler read them as two unrelated entities, the pack pages did
 * not accrue to the brand. Everything here shares one `@id` scheme so the whole site describes a
 * single connected graph.
 *
 * THE HONESTY RAIL, restated because this is where it is easiest to break. Structured data may
 * only ever describe what the page actually shows. In particular nothing here emits
 * `aggregateRating` or `review`: we have no reviews, fabricating one is an offence under the
 * DMCCA 2024 fake-review provisions, and Google drops structured data that contradicts visible
 * page content, so it would be illegal, dishonest, and ineffective at once. If a builder below
 * ever needs a fact the page does not display, the fix is to display it, not to assert it here.
 *
 * ABSOLUTE URLS. schema.org `@id`/`url` must be absolute, and `SITE_URL` is only configured in a
 * deployed build. Every builder therefore returns `undefined` when it is absent, exactly like the
 * canonical tag in `Seo.tsx`, a dev build emits no structured data rather than data pointing at
 * `undefined/pack/x`. Callers spread the result, so `undefined` simply drops the block.
 */

/** Absolute URL for a site-root-relative path, or `undefined` on an unconfigured build. */
export function absolute(path: string): string | undefined {
  if (!SITE_URL) return undefined;
  return path === '/' ? SITE_URL : `${SITE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

/** Stable entity anchors. Every node that mentions the brand points at these rather than
 *  repeating the name, so crawlers reconcile them as one entity across all pages. */
export const ORG_ID = () => (SITE_URL ? `${SITE_URL}/#organization` : undefined);
export const WEBSITE_ID = () => (SITE_URL ? `${SITE_URL}/#website` : undefined);

/**
 * The site-wide Organization. Richer than the `_document.tsx` version it replaces: a contact
 * point and `knowsAbout` are the fields that make an entity resolvable into a knowledge panel,
 * and they are also what an AI assistant quotes when asked "what is Mumchimp".
 *
 * `contactPoint` uses the real support mailbox, the same one printed on /refund, /privacy and
 * every pack page, and MX for it is verified (`dig +short MX mumchimp.com` -> `5 smtp.google.com`,
 * re-checked by `verify_store.sh` step 5; see the note on `LEGAL.contactEmail`). Do not add a
 * telephone here: we do not publish one, and a number a buyer cannot call is a false claim.
 *
 * No `sameAs`. It is the other field that helps entity resolution, and it is deliberately absent
 * because the brand has no social or reference profiles to point at. A `sameAs` listing a profile
 * that does not exist is worse than none: it is an unverifiable identity claim, which is the one
 * kind of structured data a crawler can trivially disprove.
 */
export function organizationNode(description: string): Record<string, unknown> | undefined {
  const id = ORG_ID();
  if (!id || !SITE_URL) return undefined;
  return {
    '@type': 'Organization',
    '@id': id,
    name: BRAND.name,
    legalName: LEGAL.legalName,
    url: SITE_URL,
    logo: { '@type': 'ImageObject', url: `${SITE_URL}/icon.svg` },
    // Same card the `og:image` meta nominates, from the one module that owns the path -- these
    // were two independent `/og.png` literals until 2026-08-14, so a change to one silently left
    // the Organization node describing a different image from the page's own preview.
    image: `${SITE_URL}${DEFAULT_OG_IMAGE_PATH}`,
    description,
    contactPoint: {
      '@type': 'ContactPoint',
      contactType: 'customer support',
      email: LEGAL.supportEmail,
      availableLanguage: 'English',
    },
    // What this brand is *about*. This is the field that lets an assistant answer "who sells
    // researched business ideas", it is a topical claim, not a performance claim, so it is
    // safe to state and is exactly what the catalogue demonstrably contains.
    knowsAbout: [
      'business opportunity research',
      'market validation',
      'go-to-market strategy',
      'the numbers',
      'small business ideas',
      'side hustle ideas',
    ],
  };
}

/**
 * The WebSite node, carrying a SearchAction.
 *
 * The SearchAction is what makes a sitelinks search box eligible, but it is also load-bearing for
 * AI surfaces: it tells an agent the one URL template that searches this site. A template pointing
 * at a search page that does not exist is the commonest way this node gets ignored, so note that
 * `?q=` is genuinely the catalogue's own filter: `encodeDiscoveryState` writes it
 * (`lib/discovery.ts:122`) and `decodeDiscoveryState` reads it back (`lib/discovery.ts:168`),
 * server-side, so a crawler following the template lands on a real filtered catalogue.
 */
export function webSiteNode(): Record<string, unknown> | undefined {
  const id = WEBSITE_ID();
  const orgId = ORG_ID();
  if (!id || !orgId || !SITE_URL) return undefined;
  return {
    '@type': 'WebSite',
    '@id': id,
    name: BRAND.name,
    url: SITE_URL,
    publisher: { '@id': orgId },
    inLanguage: 'en-GB',
    potentialAction: {
      '@type': 'SearchAction',
      target: { '@type': 'EntryPoint', urlTemplate: `${SITE_URL}/?q={search_term_string}` },
      'query-input': 'required name=search_term_string',
    },
  };
}

export interface Crumb {
  name: string;
  /** Site-root-relative path, e.g. `/collections/b2b`. */
  path: string;
}

/**
 * BreadcrumbList. Google renders this as the path shown *instead of* the raw URL in a result, so
 * a pack result reads "Mumchimp › Business ideas › DashFlow" rather than a 16-hex-character id.
 *
 * The final crumb is the current page and deliberately still carries its own `item` URL; omitting
 * it is also valid, but naming it keeps the list self-describing for consumers that read the graph
 * without knowing which page it came from.
 */
export function breadcrumbNode(crumbs: Crumb[]): Record<string, unknown> | undefined {
  if (!SITE_URL || crumbs.length === 0) return undefined;
  return {
    '@type': 'BreadcrumbList',
    itemListElement: crumbs.map((crumb, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: crumb.name,
      item: absolute(crumb.path),
    })),
  };
}

/** One FAQ, flattened to the plain text a crawler is allowed to see. See `faqPageNode`. */
export interface FaqEntry {
  question: string;
  /** The answer as plain text. MUST be the same prose the page renders. */
  answer: string;
}

/**
 * FAQPage.
 *
 * Google's rule is that the question and answer here must match what a visitor reads, schema
 * that says more than the page does gets the whole block dropped, and repeat offences cost the
 * site its rich-result eligibility. The FAQ page therefore does not author its answers twice:
 * it holds one structured copy (`src/lib/faqContent.ts`) that both the visible accordion and this
 * builder read, so the two cannot drift apart no matter who edits the copy later.
 *
 * FAQ rich results are now rare in Google's UI, so this is not primarily a rich-snippet play, it
 * is the cheapest way to hand a question-shaped, quotable answer to the assistants that increasingly
 * mediate this kind of purchase research.
 */
export function faqPageNode(entries: FaqEntry[]): Record<string, unknown> | undefined {
  if (entries.length === 0) return undefined;
  return {
    '@type': 'FAQPage',
    mainEntity: entries.map((entry) => ({
      '@type': 'Question',
      name: entry.question,
      acceptedAnswer: { '@type': 'Answer', text: entry.answer },
    })),
  };
}

export interface ListedItem {
  name: string;
  path: string;
}

/**
 * ItemList for a page that is a list of things (the catalogue, a facet landing page).
 *
 * `itemListOrder` is stated, and it is stated as *unordered*, which is the one thing about these
 * lists that is verifiable. Without any order the reader has to guess whether position 1 means
 * "best", a ranking claim we are not making, and the reason the field is here at all.
 *
 * It says unordered rather than newest-first because newest-first is not true. Measured against
 * the live catalogue on 2026-08-01:
 *
 *   $ curl -s https://api.mumchimp.com/catalog | python3 -c "...pairwise check on verifiedAt..."
 *   violations: 5     # e.g. index 12: 2026-06-25 immediately before 2026-07-31
 *
 * `verifiedAt` is a re-verification stamp that moves after publication, so the shelf order is not
 * a date order in the only date field a consumer can retrieve. The home page reorders again by
 * market. Declaring `ItemListOrderDescending` would therefore be asserting an ordering the data
 * disproves, exactly the kind of structured-data claim that gets a site's markup distrusted.
 */
export function itemListNode(items: ListedItem[], name: string): Record<string, unknown> | undefined {
  if (!SITE_URL || items.length === 0) return undefined;
  return {
    '@type': 'ItemList',
    name,
    numberOfItems: items.length,
    itemListOrder: 'https://schema.org/ItemListUnordered',
    itemListElement: items.map((item, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: item.name,
      url: absolute(item.path),
    })),
  };
}

/**
 * Merge nodes into one `@graph`, dropping the `undefined`s that the builders emit on an
 * unconfigured build. `Seo` accepts a single `jsonLd` object, and one graph is also the shape
 * crawlers prefer over several sibling script blocks, a node can then reference another by `@id`.
 *
 * A nested `@context` is stripped from each node. `productJsonLd` is a standalone document that
 * predates this module and still carries its own, and an inner `@context` inside a `@graph` is
 * not valid JSON-LD, it would be silently ignored along with, on some parsers, the node holding
 * it. Stripping here means callers can pass any builder's output without knowing which vintage
 * it is.
 *
 * Returns `undefined` (not an empty graph) when nothing survived, so `Seo` emits no script tag.
 */
export function graph(
  ...nodes: (Record<string, unknown> | undefined)[]
): Record<string, unknown> | undefined {
  const present = nodes
    .filter((n): n is Record<string, unknown> => n !== undefined)
    .map(({ '@context': _context, ...rest }) => rest);
  if (present.length === 0) return undefined;
  return { '@context': 'https://schema.org', '@graph': present };
}
