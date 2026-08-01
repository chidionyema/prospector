import { describe, expect, it } from 'vitest';

import {
  countryToMarket,
  DEFAULT_MARKET,
  groupByMarket,
  packMarket,
  resolveMarket,
  type MarketedPack,
} from '../market';

function pack(id: string, market?: string | null): MarketedPack {
  return { id, market };
}

describe('packMarket, the null-is-uk rule', () => {
  it('treats an absent market as "uk"', () => {
    expect(packMarket(pack('a', null))).toBe('uk');
    expect(packMarket(pack('b', undefined))).toBe('uk');
  });

  it('lower-cases a stored market', () => {
    expect(packMarket(pack('c', 'US'))).toBe('us');
  });
});

describe('countryToMarket', () => {
  it('maps US to "us"', () => {
    expect(countryToMarket('US')).toBe('us');
    expect(countryToMarket('us')).toBe('us');
  });

  it('maps GB, an unrecognised country, and a missing header to "uk"', () => {
    expect(countryToMarket('GB')).toBe('uk');
    expect(countryToMarket('FR')).toBe('uk');
    expect(countryToMarket(undefined)).toBe('uk');
    expect(countryToMarket(null)).toBe('uk');
    expect(countryToMarket('')).toBe('uk');
  });
});

describe('resolveMarket, precedence order', () => {
  it('an explicit ?market= override wins over everything else', () => {
    expect(
      resolveMarket({ queryMarket: 'us', cookieMarket: 'uk', countryHeader: 'GB' }),
    ).toBe('us');
  });

  it('the first value wins when ?market= arrives as an array (Next query parsing)', () => {
    expect(resolveMarket({ queryMarket: ['us', 'uk'] })).toBe('us');
  });

  it('falls back to the cookie when there is no query override', () => {
    expect(resolveMarket({ cookieMarket: 'us', countryHeader: 'GB' })).toBe('us');
  });

  it('falls back to the country header when there is no query override or cookie', () => {
    expect(resolveMarket({ countryHeader: 'US' })).toBe('us');
  });

  it('defaults to "uk" when nothing is present', () => {
    expect(resolveMarket({})).toBe('uk');
  });

  it('lower-cases whatever it resolves to', () => {
    expect(resolveMarket({ queryMarket: 'US' })).toBe('us');
  });

  it('an unknown ?market= is treated as absent, falling through to the cookie', () => {
    // Clamped to KNOWN_MARKETS: junk input must never become the resolved market, it would
    // empty the main shelf and, if echoed into Set-Cookie, let control chars 500 the page.
    expect(resolveMarket({ queryMarket: 'zz', cookieMarket: 'us' })).toBe('us');
  });

  it('an unknown cookie is treated as absent, falling through to the header', () => {
    expect(resolveMarket({ cookieMarket: 'evil\r\nvalue', countryHeader: 'US' })).toBe('us');
  });

  it('junk in every source still resolves to the default', () => {
    expect(resolveMarket({ queryMarket: '<script>', cookieMarket: 'zz', countryHeader: 'XX' })).toBe('uk');
  });
});

describe('groupByMarket, boost, don\'t block', () => {
  const packs = [
    pack('uk-1', 'uk'),
    pack('untagged-1', null),
    pack('us-1', 'us'),
    pack('us-2', 'us'),
    pack('uk-2', 'UK'),
  ];

  it('matching contains every pack in the resolved market, and nothing is dropped overall', () => {
    const grouped = groupByMarket(packs, 'us');
    expect(grouped.matching.map((p) => p.id)).toEqual(['us-1', 'us-2']);

    const totalGrouped =
      grouped.matching.length + grouped.others.reduce((n, g) => n + g.packs.length, 0);
    expect(totalGrouped).toBe(packs.length);
  });

  it('an untagged pack counts as "uk" for grouping, same as the API filter', () => {
    const grouped = groupByMarket(packs, DEFAULT_MARKET);
    expect(grouped.matching.map((p) => p.id).sort()).toEqual(['uk-1', 'uk-2', 'untagged-1']);
    expect(grouped.others).toHaveLength(1);
    expect(grouped.others[0].market).toBe('us');
    expect(grouped.others[0].packs.map((p) => p.id)).toEqual(['us-1', 'us-2']);
  });

  it('labels each other-market group with the shared marketLabel() helper', () => {
    const grouped = groupByMarket(packs, 'uk');
    expect(grouped.others[0].label).toBe('US');
  });

  it('a market matching is case-insensitive against the stored value', () => {
    const grouped = groupByMarket(packs, 'US');
    expect(grouped.matching.map((p) => p.id)).toEqual(['us-1', 'us-2']);
  });

  it('every pack is visible somewhere, boosting never hides', () => {
    for (const resolved of ['uk', 'us', 'fr']) {
      const grouped = groupByMarket(packs, resolved);
      const seen = [...grouped.matching, ...grouped.others.flatMap((g) => g.packs)].map(
        (p) => p.id,
      );
      expect(seen.sort()).toEqual(packs.map((p) => p.id).sort());
    }
  });

  it('returns no "others" groups when every pack matches', () => {
    const grouped = groupByMarket([pack('a', 'uk'), pack('b', null)], 'uk');
    expect(grouped.others).toEqual([]);
  });
});
