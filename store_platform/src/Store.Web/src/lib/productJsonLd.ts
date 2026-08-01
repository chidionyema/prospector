import { SITE_URL, BRAND } from '@/lib/config';
import type { Pack } from '@/lib/api/client';
import { label } from '@/lib/facets';
import { ORG_ID } from '@/lib/seo/schema';
import { packOgImagePath } from '@/lib/seo/ogImage';

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

/**
 * The refund promise, stated once. This is a real, published policy — /refund is the authored page
 * and the FAQ repeats it verbatim — which is the only reason it is allowed in structured data.
 *
 * `returnMethod` is deliberately absent. Every value schema.org offers for it describes shipping
 * something back (`ReturnByMail`, `ReturnInStore`), and there is nothing to return: a pack is a
 * download, so we simply refund. Google may treat the policy as incomplete without that field.
 * Incomplete and true beats complete and false, and the honesty rail is not negotiable for a
 * consumer-facing money claim.
 */
const RETURN_POLICY = {
  '@type': 'MerchantReturnPolicy',
  applicableCountry: 'GB',
  returnPolicyCategory: 'https://schema.org/MerchantReturnFiniteReturnWindow',
  merchantReturnDays: 14,
  returnFees: 'https://schema.org/FreeReturn',
} as const;

export function productJsonLd(pack: Pack): Record<string, unknown> {
  const offer = parsePrice(pack.price);
  const url = SITE_URL ? `${SITE_URL}/pack/${pack.id}` : undefined;
  const orgId = ORG_ID();
  // Each pack renders its own link-preview card. Naming it here is what stops a search result or
  // an assistant's citation card falling back to the generic site image for all of them.
  const image = SITE_URL ? `${SITE_URL}${packOgImagePath(pack.id)}` : undefined;
  const category = label('sector', pack.sector);

  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: pack.title,
    ...(pack.oneLine ? { description: pack.oneLine } : {}),
    ...(url ? { url } : {}),
    ...(image ? { image } : {}),
    brand: { '@type': 'Brand', name: BRAND.name },
    // A pack is a one-off download, so the pack id is its SKU. Stable across republishes,
    // which is what makes it usable as one.
    sku: pack.id,
    ...(category ? { category } : {}),
    // Every pack is written in English and sold as a paid download. Both are stated because an
    // assistant deciding whether to cite this page for a user asks exactly these two questions.
    inLanguage: 'en',
    isAccessibleForFree: false,
    // The engine's source count, which the page displays next to the title ("48 sources cited").
    // Emitted only when the pack actually carries one — an older pack without the field gets no
    // property rather than a zero, which would read as "cites nothing".
    ...(typeof pack.sourceCount === 'number' && pack.sourceCount > 0
      ? {
          additionalProperty: {
            '@type': 'PropertyValue',
            name: 'Sources cited',
            value: pack.sourceCount,
          },
        }
      : {}),
    ...(offer
      ? {
          offers: {
            '@type': 'Offer',
            ...offer,
            availability: 'https://schema.org/InStock',
            ...(url ? { url } : {}),
            ...(orgId ? { seller: { '@id': orgId } } : {}),
            hasMerchantReturnPolicy: RETURN_POLICY,
          },
        }
      : {}),
  };
}
