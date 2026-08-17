import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { formatPriceForMarket, formatChargeNote, formatApproxNote, currencyForCountry } from '../lib/fx';

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
    expect(formatPriceForMarket('49.00', 'GBP')).toBe('£49.00');
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
      expect(formatPriceForMarket('£49.00', 'GBP')).toBe('£49.00');
    });

    it('parses a four-figure price with a thousands separator', () => {
      expect(formatPriceForMarket('£1,049.00', 'GBP')).toBe('£1049.00');
    });

    it('formatChargeNote never doubles the currency symbol', () => {
      expect(formatChargeNote('£49.00', 'USD')).toBe(
        'Charged £49.00 GBP. Your card issuer sets the final rate.',
      );
      expect(formatChargeNote('£49.00', 'USD')).not.toMatch(/££/);
    });

    /**
     * The note it replaced read "£49 at today's rate", which named the wrong number: £49 is the
     * catalogue's source price, and the CONVERTED figure is the one a rate produced. A visitor
     * reading closely was told the opposite of what the page was doing.
     */
    it('never describes the GBP source price as rate-derived', () => {
      for (const c of ['USD', 'EUR'] as const) {
        expect(formatChargeNote('£49.00', c)).not.toMatch(/£49 at today/);
      }
      // The hedge belongs to the converted number, and says so without naming an amount.
      expect(formatApproxNote('USD')).toMatch(/approx/i);
      expect(formatApproxNote('USD')).not.toMatch(/£|\d/);
    });

    it('says nothing at all to a GBP buyer, who has nothing to disclose', () => {
      expect(formatChargeNote('£49.00', 'GBP')).toBe('');
      expect(formatApproxNote('GBP')).toBe('');
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

  it('formatPriceForMarket prints two decimals, like every other price', () => {
    expect(formatPriceForMarket('49.00', 'GBP')).toBe('£49.00');
    expect(formatPriceForMarket('49', 'GBP')).toBe('£49.00');
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

/**
 * The two-prices-in-one-fold defect.
 *
 * Measured on the served production build, 2026-08-05, `Fly-Client-Country: US`: the pack page
 * headline rendered `$62.23` while the buy CTA one line below rendered
 * `Unlock this pack · £49`. Same product, same fold, two currencies, and the note between them
 * described £49 as the rate-derived figure when it is the source.
 *
 * Founder decision: local currency is the anchor everywhere INCLUDING the CTA, with the GBP
 * charge disclosed at the point of purchase. These tests pin both halves of that.
 */
describe('the CTA quotes the same currency as the price above it', () => {
  const buyButton = readFileSync(
    fileURLToPath(new URL('../components/checkout/PackBuyButton.tsx', import.meta.url)),
    'utf8',
  );
  const packPage = readFileSync(
    fileURLToPath(new URL('../pages/pack/[id].tsx', import.meta.url)),
    'utf8',
  );

  it('the canonical buy button can render a non-GBP label at all', () => {
    // Before the fix this file imported only `formatPrice` (GBP-only from the API string), so
    // no prop, page or config could have made the CTA agree with the headline.
    expect(buyButton).toMatch(/formatPriceForMarket/);
    expect(buyButton).toMatch(/currency\s*[?:]/);
  });

  it('every PackBuyButton on the pack page is given the visitor currency', () => {
    const mounts = packPage.match(/<PackBuyButton[\s\S]*?\/>/g) ?? [];
    expect(mounts.length, 'pack page must mount at least the desktop and sticky buttons').toBeGreaterThanOrEqual(2);
    for (const mount of mounts) {
      expect(mount, `a PackBuyButton without currency= renders GBP beside a converted price:\n${mount}`).toMatch(
        /currency=\{currency\}/,
      );
    }
  });

  it('the pack page discloses the GBP charge next to the button', () => {
    expect(packPage).toMatch(/formatChargeNote\(pack\.price,\s*currency\)/);
  });
});

/**
 * The half-converted page.
 *
 * Fixing the fold by threading a `currency` prop left the rest of the same page behind. Measured
 * on the served production build, 2026-08-05, `GET /pack/8d5e24fbe6c1f5d3` with
 * `Fly-Client-Country: US`, AFTER the fold fix above was in place:
 *
 *   Unlock this pack · $62.23   Charged £49.00 GBP...     <- fold, threaded, correct
 *   6 / 6 · 33 sources · Verified 3 days ago    £49    <- related rail, three cards, not threaded
 *
 * The cards render through `SimilarPacks` / `PackGrid`, which have no reason to know about money,
 * so the prop had nowhere natural to travel. These tests pin the ambient answer instead: one
 * provider in `_app.tsx`, and no browse surface reaching for the GBP-only formatter.
 */
describe('currency is ambient, so no surface can be left behind', () => {
  const read = (rel: string) =>
    readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

  it('_app mounts the provider from the page props', () => {
    const app = read('../pages/_app.tsx');
    expect(app, '_app must import the provider').toMatch(/CurrencyProvider/);
    expect(app, 'the provider must be fed from pageProps, not a literal').toMatch(
      /<CurrencyProvider\s+currency=\{[^}]*pageProps[^}]*\}/,
    );
  });

  it('the provider defaults to GBP, the currency actually charged', () => {
    // A surface rendered outside a provider must degrade to the TRUE number, never to a stale
    // conversion of it.
    expect(read('../lib/currency.tsx')).toMatch(/createContext<Currency>\('GBP'\)/);
  });

  /*
   * `formatPrice` takes no currency and can only ever emit the GBP source string. Any browse
   * surface still calling it is, by construction, a surface that cannot follow the visitor.
   */
  it('no browse surface renders a price through the GBP-only formatter', () => {
    // PackBuyButton is deliberately absent: it keeps `formatPrice` for its GBP branch only,
    // because that helper passes the API's own "£49.00" through without prefixing a second
    // symbol -- the "££49" regression documented at its call site. It is covered instead by
    // "the canonical buy button can render a non-GBP label at all" above.
    for (const rel of [
      '../components/discovery/PackRow.tsx',
      '../components/discovery/CommandPalette.tsx',
    ]) {
      const src = read(rel);
      expect(src, `${rel} must not call formatPrice(`).not.toMatch(/\bformatPrice\s*\(/);
      expect(src, `${rel} must format against a currency`).toMatch(/formatPriceForMarket/);
    }
  });

  it('the cards read the currency from context rather than a prop', () => {
    // A prop would have to be added to SimilarPacks and PackGrid, and to the next layout
    // component anyone writes between a page and a card. That is the failure this replaces.
    expect(read('../components/discovery/PackRow.tsx')).toMatch(/useCurrency\(\)/);
    expect(read('../components/discovery/CommandPalette.tsx')).toMatch(/useCurrency\(\)/);
  });
});
