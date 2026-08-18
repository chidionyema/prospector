/**
 * The two money rules, pinned.
 *
 * 1. CURRENCIES ARE NEVER COMBINED. A helper that formats or totals money must refuse two
 *    currencies rather than return a number. £40 + $40 = 80 is the failure this stops, and it is
 *    the kind that gets read out loud in a meeting before anyone checks it.
 * 2. A MISSING AMOUNT IS NOT ZERO. `money(null, 'GBP')` must not render "£0.00" or a blank. A
 *    dashboard that paints an unmeasured figure as zero reports an outage as a quiet day.
 */
import { describe, expect, it } from 'vitest';

import { addCounts, addMinorUnits, money, perCurrency, symbolFor } from '@/lib/money';
import { ABSENT } from '@/lib/time';

describe('a missing number is never rendered as zero', () => {
  it('renders null as words, not £0.00', () => {
    expect(money(null, 'GBP')).toBe(ABSENT);
    expect(money(null, 'GBP')).not.toContain('0');
    expect(money(undefined, 'GBP')).toBe(ABSENT);
  });

  it('renders NaN as words rather than a figure', () => {
    expect(money(Number.NaN, 'GBP')).toBe(ABSENT);
    expect(money(Number.POSITIVE_INFINITY, 'USD')).toBe(ABSENT);
  });

  it('treats an amount with no currency as unmeasured, because it is not a figure', () => {
    expect(money(4900, null)).toBe(ABSENT);
    expect(money(4900, '')).toBe(ABSENT);
  });

  it('still renders a REAL zero, because a quiet day is a real answer', () => {
    expect(money(0, 'GBP')).toBe('£0.00');
  });
});

describe('minor units are minor units', () => {
  it('divides by 100 and keeps both decimals', () => {
    expect(money(4900, 'GBP')).toBe('£49.00');
    expect(money(1, 'GBP')).toBe('£0.01');
    expect(money(123456, 'GBP')).toBe('£1,234.56');
  });

  it('gives each currency its own symbol', () => {
    expect(money(4900, 'USD')).toBe('$49.00');
    expect(money(4900, 'EUR')).toBe('€49.00');
    expect(symbolFor('gbp')).toBe('£');
  });

  it('does not invent decimals for a currency that has none', () => {
    expect(money(4900, 'JPY')).toBe('¥4,900');
  });

  it('prints the ISO code for a currency it has no symbol for', () => {
    expect(money(4900, 'NOK')).toBe('NOK 49.00');
  });
});

describe('a helper that totals money must not accept two currencies', () => {
  it('throws rather than adding GBP to USD', () => {
    expect(() =>
      addMinorUnits([
        { currency: 'GBP', minorUnits: 4000 },
        { currency: 'USD', minorUnits: 4000 },
      ]),
    ).toThrow(/refusing to add GBP and USD/);
  });

  it('adds up one currency', () => {
    expect(
      addMinorUnits([
        { currency: 'GBP', minorUnits: 4000 },
        { currency: 'gbp', minorUnits: 900 },
      ]),
    ).toBe(4900);
  });

  it('returns an absence, not a short total, when a contributor is unmeasured', () => {
    expect(
      addMinorUnits([
        { currency: 'GBP', minorUnits: 4000 },
        { currency: 'GBP', minorUnits: null },
      ]),
    ).toBeNull();
  });
});

describe('perCurrency is the only way to reduce a mixed list', () => {
  it('returns one figure per currency and never one combined total', () => {
    const lines = perCurrency([
      { currency: 'USD', minorUnits: 2500 },
      { currency: 'GBP', minorUnits: 4000 },
      { currency: 'GBP', minorUnits: 900 },
    ]);
    expect(lines).toEqual([
      { currency: 'GBP', minorUnits: 4900 },
      { currency: 'USD', minorUnits: 2500 },
    ]);
    // The failure this exists to stop: one line holding 4000+900+2500.
    expect(lines.some((l) => l.minorUnits === 7400)).toBe(false);
  });

  it('renders two currencies as two figures with two symbols', () => {
    const rendered = perCurrency([
      { currency: 'GBP', minorUnits: 4000 },
      { currency: 'USD', minorUnits: 2500 },
    ]).map((l) => money(l.minorUnits, l.currency));
    expect(rendered).toEqual(['£40.00', '$25.00']);
  });

  it('marks a currency unmeasured when any of its rows is missing an amount', () => {
    expect(
      perCurrency([
        { currency: 'GBP', minorUnits: 4000 },
        { currency: 'GBP', minorUnits: null },
        { currency: 'USD', minorUnits: 2500 },
      ]),
    ).toEqual([
      { currency: 'GBP', minorUnits: null },
      { currency: 'USD', minorUnits: 2500 },
    ]);
  });

  it('drops a row with no currency rather than inventing one', () => {
    expect(perCurrency([{ currency: null, minorUnits: 4000 }])).toEqual([]);
  });
});

describe('counts keep an absence absent too', () => {
  it('adds plain integers', () => {
    expect(addCounts([1, 2, 3])).toBe(6);
  });

  it('returns null when a count is missing, not a short sum', () => {
    expect(addCounts([1, null, 3])).toBeNull();
  });
});
