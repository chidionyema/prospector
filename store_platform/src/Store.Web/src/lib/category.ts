/**
 * Presentation for the engine's `sector` facet: an icon and one dot colour per sector.
 *
 * This file used to infer the sector with six regexes over the pack's title and one-liner. That
 * is deleted (spec Part 10, AC-5) and must not come back. The regex table told buyers a metal
 * fabrication quoting engine was a gardening business, and on a storefront whose whole position
 * is "every claim has a clickable source", a category the browser invented is a claim with no
 * source behind it.
 *
 * The rule now: `sector` comes from the API or the pack has no category. An untagged pack gets
 * the neutral `unlabelled` treatment, honest, and visibly different from a real sector.
 *
 * Class strings are FULL LITERALS so Tailwind keeps them at build time; never interpolate them.
 *
 * `cover` (a 135deg two-stop gradient), `chip` (a tinted uppercase pill) and `accent` were deleted
 * on 2026-08-06 with the gradient product card. Nothing rendered them once the card became a
 * bordered white plate with an 8px dot, and a palette field kept "in case" is how a deleted visual
 * language comes back. `lib/cover.ts` and `ui/CoverArt.tsx` went with them -- both were already
 * unreferenced by any page.
 */
import type { IconName } from '@/components/ui/Icon';
import { SECTOR, label as facetLabel, type Sector } from '@/lib/facets';

export interface Category {
  /** The engine's sector code, or `unlabelled` when the pack carries no sector. */
  key: string;
  label: string;
  /**
   * False only for `UNLABELLED`. Callers must not render `label` when this is false: the
   * absence of a sector is shown by showing nothing, exactly as `FacetChips` already does for
   * an untagged facet. A pill reading "Not yet tagged" is a status message about our own
   * pipeline printed on a £49 product, and buyers read it as an unfinished listing rather than
   * as the honesty it was meant to be.
   */
  tagged: boolean;
  icon: IconName;
  /**
   * Background class for the 8px category dot on a product card (brand v3, 2026-08-06).
   *
   * This is the ONLY colour on a card. The dot is decorative in the a11y sense -- the sector
   * label sits immediately beside it -- so a colour-blind buyer loses nothing, which is what
   * makes an eight-value hue set legal here at all.
   *
   * Deliberately NOT derived from `cover`: those are 135deg two-stop gradients tuned to hold
   * white text, so their stops are saturated enough that eight dots side by side on one grid
   * read as a toy. These are the 500/600 steps of the same hue families.
   */
  dot: string;
}

type Palette = Pick<Category, 'icon' | 'dot'>;

const INDIGO: Palette = {
  icon: 'gavel',
  dot: 'bg-[#6366F1]',
};
const EMERALD: Palette = {
  icon: 'home',
  dot: 'bg-[#059669]',
};
const AMBER: Palette = {
  icon: 'building',
  dot: 'bg-[#D97706]',
};
const SKY: Palette = {
  icon: 'wallet',
  dot: 'bg-[#3B82F6]',
};
const SLATE: Palette = {
  icon: 'briefcase',
  dot: 'bg-[#64748B]',
};
const ROSE: Palette = {
  icon: 'handshake',
  dot: 'bg-[#E11D48]',
};
const VIOLET: Palette = {
  icon: 'code',
  dot: 'bg-[#8B5CF6]',
};
const TEAL: Palette = {
  icon: 'landmark',
  dot: 'bg-[#0D9488]',
};

/** One palette per canonical sector. Icons are `IconName` values (`components/ui/Icon.tsx`). */
const PALETTE: Record<Sector, Palette> = {
  licensing_admin: { ...SKY, icon: 'gavel' },
  employment_pay: { ...VIOLET, icon: 'money' },
  housing_rental: { ...TEAL, icon: 'home' },
  care_benefits: { ...ROSE, icon: 'handshake' },
  trades_construction: { ...AMBER, icon: 'building' },
  pets_animals: { ...EMERALD, icon: 'home' },
  creative_rights: { ...VIOLET, icon: 'shield' },
  property_probate: { ...INDIGO, icon: 'gavel' },
  energy_planning: { ...TEAL, icon: 'landmark' },
  retail_inventory: { ...AMBER, icon: 'wallet' },
  professional_services: { ...SLATE, icon: 'briefcase' },
  other: { ...SLATE, icon: 'briefcase' },
};

/**
 * The untagged treatment: a neutral cover, and NO label.
 *
 * This used to render a pill reading "Not yet tagged", chosen over inventing a plausible
 * category, which was the right call, but the wrong end of the choice. The pack is on the shelf
 * at £49; a badge announcing that our own tagging is incomplete is a defect notice, not candour,
 * and it appeared on four of the twenty-six packs live on 2026-07-31.
 *
 * `label` is retained only so the key is self-describing in a debugger; `tagged: false` is what
 * callers branch on, and `__tests__/category.test.ts` holds the two apart.
 */
export const UNLABELLED: Category = {
  key: 'unlabelled',
  label: 'Not yet tagged',
  tagged: false,
  icon: 'briefcase',
  dot: 'bg-[#A1A1AA]',
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
