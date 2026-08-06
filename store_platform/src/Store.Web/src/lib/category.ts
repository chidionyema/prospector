/**
 * Presentation for the engine's `sector` facet: an icon, and one hue per sector.
 *
 * This file used to infer the sector with six regexes over the pack's title and one-liner. That
 * is deleted (spec Part 10, AC-5) and must not come back. The regex table told buyers a metal
 * fabrication quoting engine was a gardening business, and on a storefront whose whole position
 * is "every claim has a clickable source", a category the browser invented is a claim with no
 * source behind it.
 *
 * The rule: `sector` comes from the API or the pack has no category.
 *
 * ## Why there are twelve hues here again (2026-08-06, second pass)
 *
 * Earlier the same day an eight-hue set was deleted from this file, correctly: twelve sectors
 * were mapped onto eight palettes, four pairs collided outright, and the hue was defended as a
 * "discovery affordance" it could not deliver. What replaced it was a single neutral dot -- and
 * the shelf that produced was measured as visually inert: 63 products, zero images, no colour
 * anywhere except the red crosses in the filter log. It read as documentation, not a shop.
 *
 * Both facts are true at once, and the resolution is a rule, not a compromise:
 *
 *   HUE IS DECORATION. THE LABEL IDENTIFIES.
 *
 * That is measured. Excluding the reserved red (killed) and green (survived) families, twelve
 * values cannot be held apart by eye -- after tuning, the closest pair is `trades_construction`
 * #7A4A0B and `retail_inventory` #854D0E, TWO degrees of hue apart. So no code path may depend on
 * a buyer naming a sector from its colour:
 *
 *   - the sector name renders beside the marker ALWAYS, never colour alone;
 *   - an untagged pack renders NO marker at all (see `UNLABELLED`), because a mute dot with no
 *     label beside it is decoration pretending to be information.
 *
 * Contrast and collision are held by `__tests__/categoryScale.test.ts`, which reads the tokens out
 * of `globals.css` and fails on any value under 4.5:1 on --surface2 or byte-equal to a semantic
 * token. Class strings are FULL LITERALS so Tailwind keeps them at build time; never interpolate.
 */
import type { IconName } from '@/components/ui/Icon';
import { SECTOR, label as facetLabel, type Sector } from '@/lib/facets';

export interface Category {
  /** The engine's sector code, or `unlabelled` when the pack carries no sector. */
  key: string;
  label: string;
  /**
   * False only for `UNLABELLED`. Callers must render NOTHING -- no label and no marker -- when
   * this is false. The absence of a sector is shown by showing nothing.
   *
   * A pill reading "Not yet tagged" was tried and removed: it is a status message about our own
   * pipeline printed on a £49 product, and buyers read it as an unfinished listing. A bare dot
   * with no label was tried next and is also wrong, for the opposite reason -- it is the only
   * element on the card carrying no meaning at all.
   */
  tagged: boolean;
  icon: IconName;
  /** Text colour for the sector name and the marker. Full literal. */
  ink: string;
  /** Badge fill: an alpha of the same token, so the tint can never drift from the ink on it. */
  tint: string;
}

type Palette = Pick<Category, 'icon' | 'ink' | 'tint'>;

/**
 * One palette per canonical sector. Icons are `IconName` values (`components/ui/Icon.tsx`).
 *
 * Written out per sector rather than built from shared constants: the previous version aliased
 * eight `Palette` consts across twelve sectors, and that indirection is exactly what hid the four
 * collisions. Twelve explicit rows make a duplicate visible by reading.
 *
 * The ICONS are one-per-sector too, since 2026-08-06. They used to collide in three pairs --
 * `home` for housing AND pets, `gavel` for licensing AND probate, `briefcase` for professional
 * services AND "specialist niches" -- covering 26 of the 63 live packs. That was survivable while
 * the icon was a 12px mark inside a labelled chip; it stopped being survivable when the pack cover
 * started drawing the same glyph at 96px, because the largest object on two adjacent cards was
 * then identical and the hue that was meant to separate them is two degrees apart in the worst
 * case (see above: hue is decoration). `__tests__/category.test.ts` holds the twelve apart.
 */
const PALETTE: Record<Sector, Palette> = {
  licensing_admin: {
    icon: 'gavel',
    ink: 'text-cat-licensing-admin',
    tint: 'bg-cat-licensing-admin/10',
  },
  employment_pay: {
    icon: 'money',
    ink: 'text-cat-employment-pay',
    tint: 'bg-cat-employment-pay/10',
  },
  housing_rental: {
    icon: 'home',
    ink: 'text-cat-housing-rental',
    tint: 'bg-cat-housing-rental/10',
  },
  care_benefits: {
    icon: 'handshake',
    ink: 'text-cat-care-benefits',
    tint: 'bg-cat-care-benefits/10',
  },
  trades_construction: {
    icon: 'building',
    ink: 'text-cat-trades-construction',
    tint: 'bg-cat-trades-construction/10',
  },
  pets_animals: {
    icon: 'paw',
    ink: 'text-cat-pets-animals',
    tint: 'bg-cat-pets-animals/10',
  },
  creative_rights: {
    icon: 'palette',
    ink: 'text-cat-creative-rights',
    tint: 'bg-cat-creative-rights/10',
  },
  property_probate: {
    icon: 'key',
    ink: 'text-cat-property-probate',
    tint: 'bg-cat-property-probate/10',
  },
  energy_planning: {
    icon: 'landmark',
    ink: 'text-cat-energy-planning',
    tint: 'bg-cat-energy-planning/10',
  },
  retail_inventory: {
    icon: 'package',
    ink: 'text-cat-retail-inventory',
    tint: 'bg-cat-retail-inventory/10',
  },
  professional_services: {
    icon: 'briefcase',
    ink: 'text-cat-professional-services',
    tint: 'bg-cat-professional-services/10',
  },
  other: {
    icon: 'board',
    ink: 'text-cat-other',
    tint: 'bg-cat-other/10',
  },
};

/**
 * The untagged treatment: no badge, no marker, no label.
 *
 * `label` is retained only so the key is self-describing in a debugger; `tagged: false` is what
 * callers branch on, and `__tests__/category.test.ts` holds the two apart. `ink`/`tint` are
 * neutral rather than absent so that a caller which ignores `tagged` degrades to something
 * legible instead of an unstyled element -- but a caller which ignores `tagged` is a bug, and
 * `__tests__/categoryScale.test.ts` asserts the card does not render a marker for it.
 */
export const UNLABELLED: Category = {
  key: 'unlabelled',
  label: 'Not yet tagged',
  tagged: false,
  icon: 'briefcase',
  ink: 'text-subtle',
  tint: 'bg-surface2',
};

const CATEGORIES: Record<string, Category> = Object.fromEntries(
  SECTOR.map((sector) => [
    sector,
    { key: sector, label: facetLabel('sector', sector) ?? sector, tagged: true, ...PALETTE[sector] },
  ]),
);

/**
 * The category for a pack, read from the engine's `sector` and nothing else. A pack with no
 * sector, or with one this build does not know, gets `UNLABELLED`. No pack text is inspected.
 */
export function categoryFor(input: { sector?: string | null }): Category {
  const sector = input.sector;
  if (!sector) return UNLABELLED;
  return CATEGORIES[sector] ?? UNLABELLED;
}

/** Every real sector's presentation, for legends and filter chips. Excludes `UNLABELLED`. */
export function allCategories(): Category[] {
  return SECTOR.map((sector) => CATEGORIES[sector]);
}
