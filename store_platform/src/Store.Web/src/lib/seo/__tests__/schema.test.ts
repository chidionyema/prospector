import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

/**
 * `lib/seo/schema.ts` reads `SITE_URL` from `lib/config`, which is a module-level const bound at
 * import time. Setting the env var after the fact therefore changes nothing, every test here
 * imports the module fresh, under the env it wants, through this helper.
 *
 * That is also what makes the "unconfigured build" cases below meaningful rather than accidental:
 * with no `.env` in this package the whole suite would otherwise run in exactly that state and the
 * populated assertions would all pass vacuously against `undefined`.
 */
const SITE = 'https://example.test';

async function loadSchema(siteUrl: string | undefined) {
  vi.resetModules();
  if (siteUrl === undefined) vi.stubEnv('NEXT_PUBLIC_SITE_URL', '');
  else vi.stubEnv('NEXT_PUBLIC_SITE_URL', siteUrl);
  return import('@/lib/seo/schema');
}

beforeEach(() => vi.resetModules());
afterEach(() => vi.unstubAllEnvs());

describe('absolute', () => {
  it('joins a root-relative path onto the site origin', async () => {
    const { absolute } = await loadSchema(SITE);
    expect(absolute('/faq')).toBe(`${SITE}/faq`);
    expect(absolute('faq')).toBe(`${SITE}/faq`);
  });

  it('does not leave a trailing slash on the home page', async () => {
    // `${SITE}/` and `${SITE}` are different strings to a crawler reconciling `@id`s, and the
    // canonical tag in Seo.tsx emits the bare origin. They must agree.
    const { absolute } = await loadSchema(SITE);
    expect(absolute('/')).toBe(SITE);
  });

  it('returns undefined on an unconfigured build', async () => {
    const { absolute } = await loadSchema(undefined);
    expect(absolute('/faq')).toBeUndefined();
  });
});

describe('organizationNode / webSiteNode', () => {
  it('anchors both nodes on stable @ids and cross-references them', async () => {
    const { organizationNode, webSiteNode, ORG_ID, WEBSITE_ID } = await loadSchema(SITE);
    const org = organizationNode('A description')!;
    const site = webSiteNode()!;

    expect(org['@id']).toBe(`${SITE}/#organization`);
    expect(site['@id']).toBe(`${SITE}/#website`);
    expect(ORG_ID()).toBe(org['@id']);
    expect(WEBSITE_ID()).toBe(site['@id']);
    // The whole reason this module exists: the WebSite points at the Organization by id rather
    // than repeating its name, so a crawler reads one entity instead of two.
    expect(site.publisher).toEqual({ '@id': org['@id'] });
  });

  it('carries a SearchAction whose template is the catalogue filter that actually exists', async () => {
    // `?q=` is written by encodeDiscoveryState (lib/discovery.ts:122) and read back by
    // decodeDiscoveryState (lib/discovery.ts:168). A template pointing at a search page that does
    // not exist is the commonest way this node gets ignored.
    const { webSiteNode } = await loadSchema(SITE);
    const action = webSiteNode()!.potentialAction as Record<string, unknown>;
    expect(action['@type']).toBe('SearchAction');
    expect((action.target as Record<string, unknown>).urlTemplate).toBe(
      `${SITE}/?q={search_term_string}`,
    );
    expect(action['query-input']).toBe('required name=search_term_string');
  });

  it('never claims a rating, a review, or a telephone number', async () => {
    // The honesty rail. We have no reviews; fabricating one is an offence under the DMCCA 2024
    // fake-review provisions, and we publish no phone number a buyer could call.
    const { organizationNode } = await loadSchema(SITE);
    const org = organizationNode('A description')!;
    expect(org.aggregateRating).toBeUndefined();
    expect(org.review).toBeUndefined();
    expect(JSON.stringify(org)).not.toContain('telephone');
    // Nor a `sameAs` profile list: the brand has none, and a link to a profile that does not
    // exist is an identity claim a crawler can disprove in one request.
    expect(org.sameAs).toBeUndefined();
  });

  it('publishes the real support mailbox as the contact point', async () => {
    // The same address printed on /refund, /privacy, the footer and every pack page. It must be a
    // mailbox that receives, because it is the only refund and privacy contact a buyer is given.
    const { organizationNode } = await loadSchema(SITE);
    const contact = organizationNode('A description')!.contactPoint as Record<string, unknown>;
    expect(contact).toEqual({
      '@type': 'ContactPoint',
      contactType: 'customer support',
      email: 'support@example.test',
      availableLanguage: 'English',
    });
  });

  it('emits nothing on an unconfigured build rather than URLs containing "undefined"', async () => {
    const { organizationNode, webSiteNode, ORG_ID } = await loadSchema(undefined);
    expect(organizationNode('A description')).toBeUndefined();
    expect(webSiteNode()).toBeUndefined();
    expect(ORG_ID()).toBeUndefined();
  });
});

describe('breadcrumbNode', () => {
  it('numbers the crumbs from 1 and gives every one an absolute item URL', async () => {
    const { breadcrumbNode } = await loadSchema(SITE);
    const node = breadcrumbNode([
      { name: 'Mumchimp', path: '/' },
      { name: 'Business ideas', path: '/ideas' },
      { name: 'DashFlow', path: '/pack/abc' },
    ])!;
    expect(node['@type']).toBe('BreadcrumbList');
    expect(node.itemListElement).toEqual([
      { '@type': 'ListItem', position: 1, name: 'Mumchimp', item: SITE },
      { '@type': 'ListItem', position: 2, name: 'Business ideas', item: `${SITE}/ideas` },
      { '@type': 'ListItem', position: 3, name: 'DashFlow', item: `${SITE}/pack/abc` },
    ]);
  });

  it('returns undefined for an empty trail', async () => {
    const { breadcrumbNode } = await loadSchema(SITE);
    expect(breadcrumbNode([])).toBeUndefined();
  });
});

describe('faqPageNode', () => {
  it('wraps each entry as a Question with an accepted Answer', async () => {
    const { faqPageNode } = await loadSchema(SITE);
    const node = faqPageNode([{ question: 'What is it?', answer: 'A researched pack.' }])!;
    expect(node['@type']).toBe('FAQPage');
    expect(node.mainEntity).toEqual([
      {
        '@type': 'Question',
        name: 'What is it?',
        acceptedAnswer: { '@type': 'Answer', text: 'A researched pack.' },
      },
    ]);
  });

  it('returns undefined when there are no entries', async () => {
    const { faqPageNode } = await loadSchema(SITE);
    expect(faqPageNode([])).toBeUndefined();
  });
});

describe('itemListNode', () => {
  it('states its length and its order, and resolves each item to an absolute URL', async () => {
    const { itemListNode } = await loadSchema(SITE);
    const node = itemListNode(
      [
        { name: 'One', path: '/pack/1' },
        { name: 'Two', path: '/pack/2' },
      ],
      'Test list',
    )!;
    expect(node.numberOfItems).toBe(2);
    // Explicitly unordered, so position 1 is not read as a ranking claim, and NOT
    // `ItemListOrderDescending`, because the live catalogue is measurably not date-ordered
    // (see the note on `itemListNode`). Pinned here so a future "helpful" change has to argue
    // with the measurement rather than with a comment.
    expect(node.itemListOrder).toBe('https://schema.org/ItemListUnordered');
    expect((node.itemListElement as Record<string, unknown>[])[1]).toEqual({
      '@type': 'ListItem',
      position: 2,
      name: 'Two',
      url: `${SITE}/pack/2`,
    });
  });

  it('returns undefined for an empty list', async () => {
    const { itemListNode } = await loadSchema(SITE);
    expect(itemListNode([], 'Empty')).toBeUndefined();
  });
});

describe('graph', () => {
  it('drops undefined nodes and hoists a single @context', async () => {
    const { graph } = await loadSchema(SITE);
    const out = graph({ '@type': 'A' }, undefined, { '@type': 'B' })!;
    expect(out['@context']).toBe('https://schema.org');
    expect(out['@graph']).toEqual([{ '@type': 'A' }, { '@type': 'B' }]);
  });

  it('strips a nested @context, which is invalid inside a @graph', async () => {
    // productJsonLd predates this module and still emits its own @context. Composing it without
    // stripping would produce a document some parsers ignore the offending node in entirely.
    const { graph } = await loadSchema(SITE);
    const out = graph({ '@context': 'https://schema.org', '@type': 'Product', name: 'X' })!;
    expect(out['@graph']).toEqual([{ '@type': 'Product', name: 'X' }]);
  });

  it('returns undefined, not an empty graph, when nothing survived', async () => {
    // Seo.tsx spreads this; undefined means no <script> tag at all, where `{"@graph":[]}` would
    // ship an empty structured-data block on every page of an unconfigured build.
    const { graph } = await loadSchema(SITE);
    expect(graph(undefined, undefined)).toBeUndefined();
  });
});

describe('the site graph _document.tsx serialises', () => {
  it('contains no character that would break a raw-text <script>', async () => {
    // _document.tsx renders this JSON as a text child rather than via dangerouslySetInnerHTML
    // (the react/no-danger rail), so it is NOT escaped by React and NOT escaped by JSON.stringify.
    // A `<` or `&` reaching it would corrupt the document, so _document.tsx drops the payload if
    // this ever fails, this test is what stops that silent drop shipping unnoticed.
    const { graph, organizationNode, webSiteNode } = await loadSchema(SITE);
    const serialized = JSON.stringify(
      graph(organizationNode('Researched business ideas, with a source for every claim.'), webSiteNode()),
    );
    expect(serialized).toBeDefined();
    expect(serialized).not.toMatch(/[&<>]/);
  });
});
