import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * An outage on OUR side must never render as a claim about the business.
 *
 * `getServerSideProps` used to catch ANY catalogue failure and return `packs: []`, which the
 * shelf renders as "No packs are live right now." -- a sold-out statement manufactured by our own
 * API being unreachable, on the one page the whole business runs through. This is the same rule
 * the engine already holds: a call that failed is not evidence, it defers.
 *
 * These tests drive the real `getServerSideProps` with the catalogue client mocked, rather than
 * asserting on the source text, because the thing that matters is what a visitor is TOLD.
 */
vi.mock('@/lib/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/client')>();
  return {
    ...actual,
    fetchCatalog: vi.fn(),
    fetchCatalogStats: vi.fn(),
  };
});

const { fetchCatalog, fetchCatalogStats } = await import('@/lib/api/client');
const { getServerSideProps } = await import('@/pages/index');
const { resetCatalogCache } = await import('@/lib/catalogCache');

const pack = (id: string) => ({
  id,
  title: id,
  oneLine: 'x',
  pricePence: 4900,
  sector: 'services',
  isListed: true,
}) as unknown as Awaited<ReturnType<typeof fetchCatalog>>[number];

function context() {
  return {
    query: {},
    req: { cookies: {}, headers: {} },
    res: { setHeader: vi.fn(), getHeader: vi.fn() },
  } as never;
}

async function propsFrom() {
  const result = await getServerSideProps(context());
  if (!('props' in result)) throw new Error('getServerSideProps did not return props');
  return (await result.props) as unknown as Record<string, unknown>;
}

describe('a catalogue outage is not a sold-out shelf', () => {
  beforeEach(() => {
    resetCatalogCache();
    vi.mocked(fetchCatalog).mockReset();
    vi.mocked(fetchCatalogStats).mockReset();
  });

  it('serves the last catalogue it actually fetched when the API goes down', async () => {
    vi.mocked(fetchCatalog).mockResolvedValueOnce([pack('a'), pack('b')]);
    vi.mocked(fetchCatalogStats).mockResolvedValueOnce(null);
    const good = await propsFrom();
    expect((good.packs as unknown[]).length).toBe(2);

    // The API dies. The visitor must still see a shelf.
    vi.mocked(fetchCatalog).mockRejectedValueOnce(new Error('ECONNREFUSED'));
    vi.mocked(fetchCatalogStats).mockRejectedValueOnce(new Error('ECONNREFUSED'));
    const duringOutage = await propsFrom();

    expect((duringOutage.packs as unknown[]).length).toBe(2);
    expect(duringOutage.catalogUnavailable).toBe(false);
  });

  it('says so honestly when it has never held a catalogue, rather than claiming nothing is live', async () => {
    vi.mocked(fetchCatalog).mockRejectedValueOnce(new Error('ECONNREFUSED'));
    vi.mocked(fetchCatalogStats).mockRejectedValueOnce(new Error('ECONNREFUSED'));

    const cold = await propsFrom();

    expect(cold.packs).toEqual([]);
    // The flag is what stops the shelf printing "No packs are live right now."
    expect(cold.catalogUnavailable).toBe(true);
  });

  it('a genuinely empty catalogue we DID fetch is still reported as empty, not as an outage', async () => {
    vi.mocked(fetchCatalog).mockResolvedValueOnce([]);
    vi.mocked(fetchCatalogStats).mockResolvedValueOnce(null);

    const empty = await propsFrom();

    expect(empty.packs).toEqual([]);
    expect(empty.catalogUnavailable).toBe(false);
  });

  it('does not remember a failed fetch as the last known good catalogue', async () => {
    vi.mocked(fetchCatalog).mockResolvedValueOnce([pack('a')]);
    vi.mocked(fetchCatalogStats).mockResolvedValueOnce(null);
    await propsFrom();

    vi.mocked(fetchCatalog).mockRejectedValueOnce(new Error('down'));
    vi.mocked(fetchCatalogStats).mockRejectedValueOnce(new Error('down'));
    await propsFrom();

    // A second outage still serves the ONE pack from the successful fetch -- the failure did not
    // overwrite the cache with its own empty result.
    vi.mocked(fetchCatalog).mockRejectedValueOnce(new Error('down'));
    vi.mocked(fetchCatalogStats).mockRejectedValueOnce(new Error('down'));
    const second = await propsFrom();

    expect((second.packs as unknown[]).length).toBe(1);
  });
});
