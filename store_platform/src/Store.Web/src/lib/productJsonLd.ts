import { SITE_URL, BRAND } from '@/lib/config';
import type { Pack } from '@/lib/api/client';

/**
 * schema.org Product data for a pack page.
 *
 * Pack pages are already indexable and in the sitemap, but a crawler reading one sees only
 * prose — it cannot tell that the page sells a specific thing for a specific price. This is the
 * machine-readable version of what a visitor already sees, and nothing more.
 *
 * What is deliberately absent: `aggregateRating` and `review`. We have no reviews. Inventing
 * them is an offence under the DMCCA 2024 fake-review provisions, and Google drops structured
 * data that contradicts visible page content — so it would be illegal, dishonest, and useless.
 * If reviews ever exist, they go on the page first and here second, never the other way round.
 */

// The API sends price as a display string ("£49.00"), not a number plus a currency code.
// schema.org needs them apart, and an Offer that advertises a price the checkout does not
// charge is a consumer-law problem, so an unparseable price emits NO offer rather than a guess.
const CURRENCY_BY_SYMBOL: Record<string, string> = { '£': 'GBP', $: 'USD', '€': 'EUR' };

export function parsePrice(display: string | undefined): { price: string; priceCurrency: string } | null {
  if (!display) return null;
  const symbol = Object.keys(CURRENCY_BY_SYMBOL).find((s) => display.includes(s));
  if (!symbol) return null;
  // Strip thousands separators before parsing, or "£1,299.00" reads as 1.
  const amount = display.replace(/[^\d.,]/g, '').replace(/,/g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(amount)) return null;
  return { price: amount, priceCurrency: CURRENCY_BY_SYMBOL[symbol] };
}

export function productJsonLd(pack: Pack): Record<string, unknown> {
  const offer = parsePrice(pack.price);
  const url = SITE_URL ? `${SITE_URL}/pack/${pack.id}` : undefined;

  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: pack.title,
    ...(pack.oneLine ? { description: pack.oneLine } : {}),
    ...(url ? { url } : {}),
    brand: { '@type': 'Brand', name: BRAND.name },
    // A pack is a one-off download, so the pack id is its SKU. Stable across republishes,
    // which is what makes it usable as one.
    sku: pack.id,
    ...(offer
      ? {
          offers: {
            '@type': 'Offer',
            ...offer,
            availability: 'https://schema.org/InStock',
            ...(url ? { url } : {}),
          },
        }
      : {}),
  };
}
