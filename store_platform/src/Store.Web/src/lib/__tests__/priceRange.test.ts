import { describe, expect, it } from 'vitest';
import { priceRange, priceSentence, formatGbp } from '@/lib/priceRange';

/**
 * The live shape on 2026-08-05, from `curl -s https://api.mumchimp.com/catalog`:
 * 61 packs, £29 x5, £49 x48, £79 x5, £99 x1, £149 x1, £199 x1.
 */
const LIVE = [
  ...Array(5).fill('£29.00'),
  ...Array(48).fill('£49.00'),
  ...Array(5).fill('£79.00'),
  '£99.00',
  '£149.00',
  '£199.00',
].map((price) => ({ price }));

describe('priceRange', () => {
  it('reads the catalogue exactly as the API serves it', () => {
    // The API sends "£49.00", not "49.00". `parseFloat("£49.00")` is NaN, which is how a price
    // parser silently becomes a price eraser.
    const r = priceRange(LIVE)!;
    expect(r.total).toBe(61);
    expect(r.min).toBe(29);
    expect(r.max).toBe(199);
    expect(r.mode).toBe(49);
    expect(r.modeCount).toBe(48);
    expect(r.uniform).toBe(false);
    expect(r.label).toBe('£29 to £199');
    expect(r.headline).toBe('From £29 a pack.');
  });

  it('states the mode alongside the spread, never the floor alone', () => {
    // "From £29" on a shelf where 48 of 61 packs are £49 is true and misleading, which is the
    // exact failure the six checks exist to catch when a PACK does it.
    const sentence = priceSentence(priceRange(LIVE)!);
    expect(sentence).toContain('48 of the 61');
    expect(sentence).toContain('£49');
    expect(sentence).toContain('£29 to £199');
  });

  it('still says "every pack is £X" when that is true again', () => {
    // The ladder can collapse back to one price. The copy must follow the data in both
    // directions, or the next uniform catalogue gets described as a range.
    const r = priceRange(Array(12).fill({ price: '£49.00' }))!;
    expect(r.uniform).toBe(true);
    expect(r.headline).toBe('£49 a pack.');
    expect(priceSentence(r)).toBe('Every pack is £49. One payment, no subscription, no upsell.');
  });

  it('returns null rather than a guess when the shelf cannot be read', () => {
    // Every caller renders no price claim on null. A pricing page that quotes a number it could
    // not verify is worse than one that says "see the pack".
    expect(priceRange([])).toBeNull();
    expect(priceRange([{ price: '' }, { price: null }, { price: 'TBC' }])).toBeNull();
    expect(priceRange([{ price: '£0.00' }])).toBeNull();
  });

  it('keeps pence when there are pence, and drops them when there are not', () => {
    expect(formatGbp(49)).toBe('£49');
    expect(formatGbp(49.5)).toBe('£49.50');
  });

  it('breaks a tie to the cheaper price', () => {
    // Arbitrary either way, but the cheaper one is the number a buyer can act on without
    // discovering an upsell.
    const r = priceRange([{ price: '£29.00' }, { price: '£29.00' }, { price: '£79.00' }, { price: '£79.00' }])!;
    expect(r.mode).toBe(29);
  });
});
