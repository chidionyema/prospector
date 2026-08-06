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

  it('gives every sector its own icon, no two share a glyph', () => {
    /*
     * Added 2026-08-06, after the pack cover started drawing the sector icon at 96px.
     *
     * Three pairs shared one glyph until that day -- `home` for housing_rental AND pets_animals,
     * `gavel` for licensing_admin AND property_probate, `briefcase` for professional_services AND
     * other -- covering 26 of the 63 packs live at the time. It was invisible while the icon was a
     * 12px mark inside a chip that spelled the sector out beside it. It stopped being invisible
     * when the same glyph became the largest object on the card: two adjacent cards from a
     * colliding pair were, at a glance, the same picture, and the hue meant to separate them is
     * two degrees apart in the worst case (`category.ts` header: hue is decoration).
     *
     * Reported as the collision, not as a count, so a failure names the sectors to fix.
     */
    const byIcon = new Map<string, string[]>();
    for (const cat of allCategories()) {
      byIcon.set(cat.icon, [...(byIcon.get(cat.icon) ?? []), cat.key]);
    }
    const collisions = [...byIcon.entries()].filter(([, keys]) => keys.length > 1);
    expect(collisions.map(([icon, keys]) => `${icon}: ${keys.join(' + ')}`)).toEqual([]);
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

  // `dot` is gone (2026-08-06, second pass) along with the single neutral marker it named. The
  // untagged treatment is now to render NOTHING -- no badge, no marker, no label -- because a dot
  // with no word beside it was the only element on the card carrying no meaning at all.
  //
  // `ink`/`tint` still have to be non-empty even though the card is not supposed to render them:
  // they are the graceful degradation for a caller that forgets to branch on `tagged`, so the
  // failure mode is a neutral badge rather than an unstyled one. That a caller which forgets is
  // a BUG is asserted separately, against the rendered card, in `__tests__/categoryScale.test.ts`.
  it('carries neutral ink and tint, so a caller that ignores `tagged` degrades legibly', () => {
    expect(UNLABELLED.ink).not.toBe('');
    expect(UNLABELLED.tint).not.toBe('');
    expect(UNLABELLED.icon).not.toBe('');
  });

  it('is the only untagged category, every real sector is tagged', () => {
    expect(allCategories().every((c) => c.tagged)).toBe(true);
    expect(allCategories().map((c) => c.key)).not.toContain(UNLABELLED.key);
  });
});
