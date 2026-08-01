import { describe, it, expect } from 'vitest';
import { parsePrice, productJsonLd } from '@/lib/productJsonLd';
import type { Pack } from '@/lib/api/client';

const pack = (over: Partial<Pack> = {}): Pack =>
  ({
    id: '7dc94c897c7d28f4',
    title: 'IHT Valuation Barometer',
    oneLine: 'Challenge HMRC inheritance tax valuations with evidence of what HMRC settles for.',
    price: '£49.00',
    paymentProvider: 'stripe',
    providerPriceId: 'price_test',
    ...over,
  }) as Pack;

describe('parsePrice', () => {
  it('splits the display string into an amount and a currency code', () => {
    expect(parsePrice('£49.00')).toEqual({ price: '49.00', priceCurrency: 'GBP' });
    expect(parsePrice('$49.00')).toEqual({ price: '49.00', priceCurrency: 'USD' });
    expect(parsePrice('€10')).toEqual({ price: '10', priceCurrency: 'EUR' });
  });

  it('strips thousands separators rather than truncating at them', () => {
    // "£1,299.00" naively parsed with parseFloat gives 1. That would advertise a £1,299 pack
    // at one pound in search results, the exact mismatch this function exists to prevent.
    expect(parsePrice('£1,299.00')).toEqual({ price: '1299.00', priceCurrency: 'GBP' });
  });

  it('returns null rather than guessing when it cannot parse', () => {
    // No offer is emitted in these cases. An Offer advertising a price the checkout does not
    // charge is a consumer-law problem, so silence is the only safe failure.
    expect(parsePrice('49.00')).toBeNull(); // no currency symbol
    expect(parsePrice('Free')).toBeNull();
    expect(parsePrice('')).toBeNull();
    expect(parsePrice(undefined)).toBeNull();
  });
});

describe('productJsonLd', () => {
  it('describes the product and its offer', () => {
    const ld = productJsonLd(pack());
    expect(ld['@type']).toBe('Product');
    expect(ld.name).toBe('IHT Valuation Barometer');
    expect(ld.sku).toBe('7dc94c897c7d28f4');
    expect(ld.offers).toMatchObject({ price: '49.00', priceCurrency: 'GBP' });
  });

  it('omits the offer entirely when the price cannot be parsed', () => {
    expect(productJsonLd(pack({ price: 'TBC' })).offers).toBeUndefined();
  });

  it('never claims a rating or a review', () => {
    // We have no reviews. Emitting either would be a DMCCA 2024 fake-review offence, and Google
    // drops structured data that contradicts the visible page. This test is the fence: if
    // someone adds ratings here, they have to delete this to do it.
    const ld = productJsonLd(pack());
    expect(ld.aggregateRating).toBeUndefined();
    expect(ld.review).toBeUndefined();
    expect(JSON.stringify(ld)).not.toMatch(/rating|review/i);
  });
});
