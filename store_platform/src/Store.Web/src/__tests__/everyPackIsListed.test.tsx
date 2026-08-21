// @vitest-environment jsdom
import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import type { Pack } from '@/lib/api/client';
import type { Props } from '@/pages/packs';

/**
 * `/packs` MUST list the whole catalogue. Nothing here asserts appearance.
 *
 * FR-10 of `docs/FIRST_RUN_AND_NAVIGATION_PROGRAM.md`. Measured 2026-08-21 against live: 14 of
 * 77 packs were reachable from no page in fewer than three clicks, because the home page caps
 * its shelf (`pages/index.tsx:1445`, `:1494`) and `/ideas` links categories rather than packs.
 * `/packs` is the page that closes that gap, and it closes it only while it holds nothing back.
 *
 * THE FAILURE THIS EXISTS TO CATCH is one character: a `.slice(0, n)` added to this page for a
 * perfectly good reason (it got long, it got slow), which silently returns 14 packs -- or 40 --
 * to being three clicks from everywhere with every test still green. The count is not asserted
 * against a number written here; it is asserted against the catalogue the page was given, so a
 * catalogue of any size grades itself and the test never needs editing as the shelf grows.
 *
 * Both halves are measured, because a cap can be added in either place: `getServerSideProps` can
 * drop packs before the component sees them, and the component can drop packs it was given.
 */

const pack = (id: string, market: string): Pack =>
  ({
    id,
    title: `Pack ${id}`,
    oneLine: 'A one-line description.',
    price: '£99',
    paymentProvider: 'stripe',
    providerPriceId: `price_${id}`,
    market,
  }) as unknown as Pack;

/** Two markets and an odd count, so a grouped renderer that drops a whole group fails too. */
const CATALOGUE: Pack[] = [
  ...Array.from({ length: 9 }, (_, i) => pack(`uk${i}`, 'uk')),
  ...Array.from({ length: 4 }, (_, i) => pack(`us${i}`, 'us')),
];

vi.mock('@/lib/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/client')>()),
  fetchCatalog: vi.fn(async () => CATALOGUE),
}));

// The page's chrome is not under test and pulls in `next/router`, which has no provider here.
// Passthroughs, so what is measured is the page's own output and nothing else.
vi.mock('@/components/marketing/MarketingLayout', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/Seo', () => ({ Seo: () => null }));
vi.mock('@/components/marketing/blocks', () => ({
  PageHero: () => null,
  Section: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
  CtaBand: () => null,
}));

const load = async () => await import('@/pages/packs');

/* The first `await import` transforms the page and everything it pulls in -- the layout, the row,
   the fx tables. Measured 2026-08-21 on this laptop at 6.8s, against vitest's 5000ms default,
   which is a wall-clock limit and so is a function of how many gates are running beside you. The
   test is not slow; the harness is shared. An explicit budget here rather than a global one,
   because the global default is a shared rail another session is already changing. */
const SLOW_IMPORT_MS = 30_000;

const ctx = () =>
  ({
    req: { headers: {}, cookies: {} },
    res: { statusCode: 200, setHeader: vi.fn() },
    query: {},
  }) as never;

describe('/packs lists every pack the catalogue holds', () => {
  beforeEach(() => vi.clearAllMocks());

  it('hands the component the whole catalogue, not a page of it', async () => {
    const { getServerSideProps } = await load();
    const result = (await getServerSideProps(ctx())) as { props: Props };

    const listed = result.props.groups.flatMap((group) => group.packs);
    expect(new Set(listed.map((p) => p.id))).toEqual(new Set(CATALOGUE.map((p) => p.id)));
    expect(listed).toHaveLength(CATALOGUE.length);
    expect(result.props.total).toBe(CATALOGUE.length);
  }, SLOW_IMPORT_MS);

  it('renders one link per pack it was given', async () => {
    const mod = await load();
    const AllPacks = mod.default;
    const result = (await mod.getServerSideProps(ctx())) as { props: Props };

    render(<AllPacks {...result.props} />);

    const hrefs = screen
      .getAllByRole('link')
      .map((a) => a.getAttribute('href') ?? '')
      .filter((href) => href.startsWith('/pack/'));

    expect(new Set(hrefs)).toEqual(new Set(CATALOGUE.map((p) => `/pack/${p.id}`)));
  }, SLOW_IMPORT_MS);

  it('serves a real 503 rather than a 404 when the catalogue is unreachable', async () => {
    const client = await import('@/lib/api/client');
    vi.mocked(client.fetchCatalog).mockRejectedValueOnce(new Error('down'));
    vi.spyOn(console, 'error').mockImplementation(() => {});

    const res = { statusCode: 200, setHeader: vi.fn() };
    const { getServerSideProps } = await load();
    const result = (await getServerSideProps({
      req: { headers: {}, cookies: {} },
      res,
      query: {},
    } as never)) as { props: Props };

    // `notFound: true` here would override the status and serve a 404, which is grounds for
    // dropping the page from the index over a two-second API blip. Measured 2026-08-01.
    expect(result).not.toHaveProperty('notFound');
    expect(res.statusCode).toBe(503);
    expect(res.setHeader).toHaveBeenCalledWith('Retry-After', '120');
    expect(result.props.unavailable).toBe(true);
  }, SLOW_IMPORT_MS);
});
