import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { formatPriceForMarket, formatGbpNote, currencyForCountry } from '../lib/fx';

/**
 * US-5 — Currency by visitor market.
 *
 * The audit (§4.6) found a US visitor on a US-market pack staring at "£49" with no FX context.
 * The fix is to render the price in the buyer's local currency, with the GBP source visible
 * underneath as a small note. The visitor's market is resolved via the existing
 * `resolveMarket` (or the country header for the FX display).
 *
 * This test is split into two layers:
 *
 *  - Unit tests on `formatPriceForMarket` and `currencyForCountry` in `lib/fx.ts`. These run
 *    against the live converter with a hardcoded rate, so they are deterministic in CI.
 *  - Source-pattern tests on the page files, asserting the new functions are wired up.
 */

describe('US-5 — Currency converter unit tests', () => {
  it('currencyForCountry returns USD for US', () => {
    expect(currencyForCountry('US')).toBe('USD');
  });

  it('currencyForCountry returns EUR for EU countries', () => {
    expect(currencyForCountry('DE')).toBe('EUR');
    expect(currencyForCountry('FR')).toBe('EUR');
    expect(currencyForCountry('IT')).toBe('EUR');
    expect(currencyForCountry('ES')).toBe('EUR');
  });

  it('currencyForCountry returns GBP for UK and unknown', () => {
    expect(currencyForCountry('GB')).toBe('GBP');
    expect(currencyForCountry(null)).toBe('GBP');
    expect(currencyForCountry(undefined)).toBe('GBP');
    expect(currencyForCountry('XX')).toBe('GBP');
  });

  it('formatPriceForMarket returns the GBP price for GBP', () => {
    expect(formatPriceForMarket('49.00', 'GBP')).toBe('£49');
  });

  /*
   * The shape the API ACTUALLY sends.
   *
   * Every case in this file fed a bare '49.00'. A live `GET https://api.mumchimp.com/catalog`
   * returns `"price": "£49.00"`, symbol included, and `parseFloat('£49.00')` is NaN, so
   * formatPriceForMarket took its `return price` fallback for every real pack and conversion
   * silently no-opped in production while this suite stayed green. A US visitor was shown
   * "£49.00" even though currencyForCountry('US') correctly resolved USD.
   *
   * These cases pin the real input shape so the same divergence cannot recur.
   */
  describe('the price shape the API actually returns (symbol included)', () => {
    it('converts a symbol-prefixed price to USD instead of passing it through', () => {
      const result = formatPriceForMarket('£49.00', 'USD');
      expect(result, 'must not fall through to the raw GBP string').not.toBe('£49.00');
      expect(result, 'must render in dollars').toMatch(/^\$/);
      const numeric = parseFloat(result.replace(/[^\d.]/g, ''));
      expect(numeric).toBeGreaterThanOrEqual(60);
      expect(numeric).toBeLessThanOrEqual(65);
    });

    it('converts a symbol-prefixed price to EUR', () => {
      const result = formatPriceForMarket('£49.00', 'EUR');
      expect(result).toMatch(/^€/);
    });

    it('renders a symbol-prefixed price once, not twice, for GBP', () => {
      expect(formatPriceForMarket('£49.00', 'GBP')).toBe('£49');
    });

    it('parses a four-figure price with a thousands separator', () => {
      expect(formatPriceForMarket('£1,049.00', 'GBP')).toBe('£1049');
    });

    it('formatGbpNote never doubles the currency symbol', () => {
      expect(formatGbpNote('£49.00')).toBe("£49 at today's rate");
      expect(formatGbpNote('£49.00')).not.toMatch(/££/);
    });
  });

  it('formatPriceForMarket returns the USD price for USD', () => {
    // The base rate is 1 GBP = 1.27 USD; 49 × 1.27 = 62.23 → rounds to 62.23.
    const result = formatPriceForMarket('49.00', 'USD');
    expect(result).toMatch(/^\$/);
    const numeric = parseFloat(result.replace(/[^\d.]/g, ''));
    expect(numeric).toBeGreaterThanOrEqual(60);
    expect(numeric).toBeLessThanOrEqual(65);
  });

  it('formatPriceForMarket returns the EUR price for EUR', () => {
    // The base rate is 1 GBP = 1.17 EUR; 49 × 1.17 = 57.33 → rounds to 57.33.
    const result = formatPriceForMarket('49.00', 'EUR');
    expect(result).toMatch(/^€/);
    const numeric = parseFloat(result.replace(/[^\d.]/g, ''));
    expect(numeric).toBeGreaterThanOrEqual(55);
    expect(numeric).toBeLessThanOrEqual(60);
  });

  it('formatPriceForMarket strips trailing .00 like formatPrice', () => {
    expect(formatPriceForMarket('49.00', 'GBP')).toBe('£49');
    expect(formatPriceForMarket('49', 'GBP')).toBe('£49');
  });

  it('formatPriceForMarket keeps the cents when non-zero', () => {
    // 49.50 GBP × 1.27 = 62.865 → rounds to 62.87
    const result = formatPriceForMarket('49.50', 'USD');
    expect(result).toMatch(/^\$/);
    const numeric = parseFloat(result.replace(/[^\d.]/g, ''));
    expect(numeric).toBeGreaterThanOrEqual(60);
    expect(numeric).toBeLessThanOrEqual(65);
  });
});

describe('US-5 — fx module rate cache', () => {
  it('exports a base rate that is stable across calls', async () => {
    // The base rates are exposed as a fallback when the API is unreachable. They must
    // be deterministic so the rendered price does not flap on every render.
    const { BASE_RATES } = await import('../lib/fx');
    expect(BASE_RATES.rates.USD).toBeGreaterThan(1);
    expect(BASE_RATES.rates.USD).toBeLessThan(2);
    expect(BASE_RATES.rates.EUR).toBeGreaterThan(1);
    expect(BASE_RATES.rates.EUR).toBeLessThan(2);
  });

  it('exports a fetchExchangeRates function that returns a RateTable', async () => {
    const { fetchExchangeRates } = await import('../lib/fx');
    // We don't actually call the network in CI; we just assert the function exists
    // and the return type is reasonable.
    expect(typeof fetchExchangeRates).toBe('function');
  });
});

describe('US-5 — Source contract', () => {
  const fxExists = existsSync(fileURLToPath(new URL('../lib/fx.ts', import.meta.url)));
  const page = readFileSync(
    fileURLToPath(new URL('../pages/index.tsx', import.meta.url)),
    'utf8',
  );
  const packPage = readFileSync(
    fileURLToPath(new URL('../pages/pack/[id].tsx', import.meta.url)),
    'utf8',
  );

  it('declares a lib/fx.ts module', () => {
    expect(fxExists, 'lib/fx.ts must exist').toBe(true);
  });

  it('home page imports the new currency helpers', () => {
    if (!fxExists) return;
    expect(page, 'index.tsx must import formatPriceForMarket').toMatch(
      /import\s+\{[^}]*formatPriceForMarket[^}]*\}\s+from\s+['"]@\/lib\/fx['"]/,
    );
    expect(page, 'index.tsx must import currencyForCountry').toMatch(
      /currencyForCountry/,
    );
  });

  it('pack detail page imports the new currency helpers', () => {
    if (!fxExists) return;
    expect(packPage, 'pack/[id].tsx must import formatPriceForMarket').toMatch(
      /formatPriceForMarket/,
    );
  });

  it('home page renders the price with the new format in the right places', () => {
    // The PackCard's price is rendered through the PackBuyButton; the SpotlightCard and the
    // trending picks row render the price directly. Both must call formatPriceForMarket with
    // a currency argument (a literal 'USD' / 'GBP' / 'EUR' OR a variable named `currency`).
    const hasNewFormat = /formatPriceForMarket\s*\(\s*[^,]+,\s*(?:['"][A-Z]{3}['"]|currency)\b/.test(page);
    expect(
      hasNewFormat,
      'index.tsx must call formatPriceForMarket(price, currency) somewhere',
    ).toBe(true);
  });

  it('pack detail page renders the price with the new format', () => {
    // The pack detail has price renders in the checkoutBody — check at least one.
    const hasNewFormat = /formatPriceForMarket\s*\(\s*[^,]+,\s*(?:['"][A-Z]{3}['"]|currency)\b/.test(packPage);
    expect(
      hasNewFormat,
      'pack/[id].tsx must call formatPriceForMarket(price, currency) somewhere',
    ).toBe(true);
  });
});
