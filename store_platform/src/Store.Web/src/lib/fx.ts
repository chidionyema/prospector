/**
 * Currency conversion for the storefront.
 *
 * US-5 (audit §4.6): a US visitor on a US-market pack was staring at "£49" with no FX context.
 * The fix is to render the price in the buyer's local currency, with the GBP source visible
 * underneath as a small note. The buyer keeps paying in GBP (the store's source of truth is
 * the Stripe price configured at publish time); the display side is purely a courtesy.
 *
 * Architecture:
 *
 *  - `formatPriceForMarket(price, currency)` is the pure render function. Callers pass the
 *    currency; the function does the math.
 *  - `currencyForCountry(country)` maps an ISO-3166 country code to the currency. The market
 *    (`uk` / `us`) and the currency are decoupled: the market decides which packs to show
 *    first, the country decides which currency to display. A US visitor sees US packing first
 *    AND the price in dollars; a French visitor sees UK packing first (no EU market yet) AND
 *    the price in euros.
 *  - `fetchExchangeRates()` returns the live GBP→USD/EUR rates, with a 24-hour cache and a
 *    hardcoded fallback (`BASE_RATES`) when the API is unreachable. The fallback is what the
 *    render path uses by default; the live fetch is opportunistic.
 *
 * Decoupling currency from market matters: the audit's "EUR for `eu`" reads as a market
 * code, but there is no `eu` market in the catalogue yet. The country-to-currency function
 * is the seam that lets the display side extend without the catalogue side having to.
 */
import { fetchFxRates } from '@/lib/api/client';

export type Currency = 'GBP' | 'USD' | 'EUR';

export interface RateTable {
  base: 'GBP';
  rates: Record<Exclude<Currency, 'GBP'>, number>;
  /** Epoch ms when the rates were fetched. 0 means "use the fallback only". */
  fetchedAt: number;
}

/**
 * Fallback rates (1 GBP = X). Updated 2026-08-04 from open.er-api.com. The fallback is
 * what every render uses until the live fetch succeeds; the live fetch is opportunistic
 * and silently skipped on any failure (the checkout still charges the buyer in GBP, so a
 * stale rate is a UX problem, never a money problem).
 */
export const BASE_RATES: RateTable = {
  base: 'GBP',
  rates: {
    USD: 1.27,
    EUR: 1.17,
  },
  fetchedAt: 0,
};

/** ISO-3166 alpha-2 codes of the 27 EU member states. Used to map a country code to EUR. */
const EU_COUNTRIES: ReadonlySet<string> = new Set([
  'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR',
  'DE', 'GR', 'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL',
  'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
]);

const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

/** In-memory cache for the live rates. */
let cachedRates: RateTable = BASE_RATES;
let pendingFetch: Promise<RateTable> | null = null;

/**
 * Map an ISO-3166 alpha-2 country code to the currency the storefront should display.
 * Unknown / missing codes fall through to GBP; the rendering side does the same fallback so
 * a buyer whose country the storefront does not know still sees a price.
 */
export function currencyForCountry(country?: string | null): Currency {
  const code = (country ?? '').trim().toUpperCase();
  if (code === 'US') return 'USD';
  if (EU_COUNTRIES.has(code)) return 'EUR';
  return 'GBP';
}

/**
 * Format a price string in the given currency. The input is what the API returns, e.g.
 * "49.00" or "49.50" (the catalogue only ever holds GBP, this is the source of truth). The
 * output is the rendered string, e.g. "$61" or "€57.33".
 *
 * The function is intentionally pure: it does not mutate the cache, it does not fetch. Pass
 * the current rates via `getRates()` if you want live data; the fallback is fine for a
 * single render.
 */
export function formatPriceForMarket(
  price: string,
  currency: Currency,
  rates: Record<Exclude<Currency, 'GBP'>, number> = BASE_RATES.rates,
): string {
  // The catalogue stores price as a decimal string ("49.00", "49.50"). parseFloat is
  // fine here because the format is well-defined and we never see exponential notation.
  const gbp = parseFloat(price);
  if (!Number.isFinite(gbp)) return price;

  if (currency === 'GBP') {
    return `£${formatNumber(gbp)}`;
  }

  const rate = rates[currency];
  if (!Number.isFinite(rate)) return `£${formatNumber(gbp)}`; // fallback
  const converted = gbp * rate;
  const symbol = currency === 'USD' ? '$' : '€';
  return `${symbol}${formatNumber(converted)}`;
}

/**
 * Format the GBP equivalent as a small note, e.g. "£49 at today's rate". Rendered under the
 * headline price for non-GBP buyers so the source of truth is never hidden.
 */
export function formatGbpNote(price: string): string {
  const gbp = parseFloat(price);
  if (!Number.isFinite(gbp)) return `£${price}`;
  return `£${formatNumber(gbp)} at today's rate`;
}

function formatNumber(n: number): string {
  // Round to the nearest whole unit when the converted value is >= 100, otherwise keep
  // two decimals. £49.00 → "49"; $62.23 → "62.23"; €57.33 → "57.33".
  if (n >= 100) return Math.round(n).toString();
  // toFixed(2) gives "62.23"; trim trailing zeros so "57.30" becomes "57.3".
  const fixed = n.toFixed(2);
  return fixed.replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
}

/**
 * Fetch the live GBP exchange rates. Cached for 24 hours. Falls back to BASE_RATES on any
 * failure. Safe to call multiple times; concurrent calls share a single in-flight request.
 *
 * The underlying `fetch` lives in `@/lib/api/client.ts` (FX_FETCH) — the UI-STANDARDS rule
 * "Components never call fetch directly" applies to `/lib/fx.ts` too, and the right place
 * for raw HTTP is the API client. We expose a typed result here so the rendering side
 * remains a pure function of the cached rates.
 */
export async function fetchExchangeRates(): Promise<RateTable> {
  // Cache hit: still fresh.
  if (cachedRates.fetchedAt > 0 && Date.now() - cachedRates.fetchedAt < CACHE_TTL_MS) {
    return cachedRates;
  }

  // Dedup: a second caller while one is in flight awaits the same promise.
  if (pendingFetch) return pendingFetch;

  pendingFetch = (async () => {
    try {
      const data = await fetchFxRates();
      const usdPerGbp = 1 / (data?.rates?.GBP ?? 1 / BASE_RATES.rates.USD);
      const eurPerGbp = usdPerGbp * (data?.rates?.EUR ?? BASE_RATES.rates.EUR);
      const next: RateTable = {
        base: 'GBP',
        rates: { USD: usdPerGbp, EUR: eurPerGbp },
        fetchedAt: Date.now(),
      };
      cachedRates = next;
      return next;
    } catch {
      // Network failure: return the fallback. The buyer still pays in GBP; the display
      // is a courtesy, so a stale rate is a UX footnote, not a correctness issue.
      return BASE_RATES;
    } finally {
      pendingFetch = null;
    }
  })();

  return pendingFetch;
}

/** Get the current rates synchronously (the cache, fallback if no fetch has succeeded). */
export function getRates(): RateTable {
  return cachedRates;
}
