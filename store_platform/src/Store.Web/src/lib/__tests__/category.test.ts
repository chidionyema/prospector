import { describe, expect, it } from 'vitest';

import { allCategories, categoryFor, UNLABELLED } from '../category';
import { SECTOR, label as facetLabel } from '../facets';

/**
 * Two rules this file holds, both of which the storefront broke once.
 *
 * 1. A category is never inferred. The sector comes from the API or there is no category,
 *    the deleted regex table told buyers a metal-fabrication quoting engine was a gardening
 *    business, and an invented category is an unsourced claim on a storefront that sells
 *    "every claim has a clickable source".
 * 2. An untagged pack renders no label. `tagged` is the flag callers branch on, and it is
 *    deliberately not derived from `label` being empty, `UNLABELLED.label` still holds a
 *    developer-facing string, so a caller that reached for the label instead of the flag would
 *    print "Not yet tagged" on a £49 product and nothing here would notice. Hence both are
 *    asserted, separately.
 */
describe('categoryFor', () => {
  it('returns the engine sector when it is one this build knows', () => {
    const cat = categoryFor({ sector: 'trades_construction' });
    expect(cat.key).toBe('trades_construction');
    expect(cat.tagged).toBe(true);
    expect(cat.label).toBe(facetLabel('sector', 'trades_construction'));
  });

  it('covers every member of the sector vocabulary', () => {
    // Guards against a sector added to facets.ts with no palette: the lookup would fall through
    // to UNLABELLED and a real, engine-assigned sector would silently stop rendering.
    for (const sector of SECTOR) {
      expect(categoryFor({ sector }).key, sector).toBe(sector);
    }
  });

  it.each([
    ['absent', undefined],
    ['null', null],
    ['empty', ''],
    ['a sector this build does not know', 'quantum_llama_farming'],
  ])('is untagged when the sector is %s', (_name, sector) => {
    expect(categoryFor({ sector })).toBe(UNLABELLED);
  });
});

describe('the untagged treatment', () => {
  it('is not tagged, so no caller may render its label', () => {
    expect(UNLABELLED.tagged).toBe(false);
  });

  it('still carries a cover and an icon, so an untagged card is neutral, not broken', () => {
    expect(UNLABELLED.cover).not.toBe('');
    expect(UNLABELLED.icon).not.toBe('');
  });

  it('is the only untagged category, every real sector is tagged', () => {
    expect(allCategories().every((c) => c.tagged)).toBe(true);
    expect(allCategories().map((c) => c.key)).not.toContain(UNLABELLED.key);
  });
});
