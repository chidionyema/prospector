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
   * Background class for the 8px marker beside the sector label on a product card.
   *
   * NEUTRAL, and one value for every category. This replaced an eight-hue set (#6366F1 indigo,
   * #059669 emerald, #D97706 amber, #3B82F6 sky, #64748B slate, #E11D48 rose, #8B5CF6 violet,
   * #0D9488 teal) on 2026-08-06, for two measured reasons.
   *
   * 1. The hue could not identify a category, so it was never the discovery affordance it was
   *    defended as. Twelve sectors were mapped onto eight palettes, and four pairs collided
   *    outright: employment_pay and creative_rights were both VIOLET, housing_rental and
   *    energy_planning both TEAL, trades_construction and retail_inventory both AMBER,
   *    professional_services and other both SLATE. No buyer could tell those apart by colour,
   *    which is the whole claim a category hue has to make.
   * 2. They were the last hardcoded hex in `src/`, outside the token scale entirely, against a
   *    direction of a neutral grey scale with hairline borders. On the money page the rose dot
   *    measured as the ONLY red element on the whole page (rgb(225,29,72), 390x844) -- on a site
   *    where red means KILLED in the filter log and the kill log, and nothing else.
   *
   * `--subtle` because this is the smallest ink allowed to read at all next to `--muted` text;
   * `--faint` is documented as decoration that may never carry information, and at 8px it is
   * invisible. The marker is still `aria-hidden`: the sector name sits immediately beside it and
   * carries the meaning, which is what makes a purely decorative marker legal here.
   *
   * Held to one value by `__tests__/noArbitraryHex.test.ts`, which fails on any `bg-[#...]` in
   * `src/` -- a palette drifts back one hex at a time, and a comment does not stop it.
   */
  dot: string;
}

type Palette = Pick<Category, 'icon' | 'dot'>;

/**
 * One marker treatment for every tagged category. See the `dot` docblock above for why the hue
 * set went: it collided four ways, so it identified nothing, and it was the last hardcoded hex.
 *
 * The palette constants below keep their old names. They now differ only by icon, which is the
 * thing that actually distinguishes a category on the card, and renaming them to their icon
 * would churn every row of PALETTE for no behaviour change.
 */
const DOT = 'bg-subtle';

const INDIGO: Palette = {
  icon: 'gavel',
  dot: DOT,
};
const EMERALD: Palette = {
  icon: 'home',
  dot: DOT,
};
const AMBER: Palette = {
  icon: 'building',
  dot: DOT,
};
const SKY: Palette = {
  icon: 'wallet',
  dot: DOT,
};
const SLATE: Palette = {
  icon: 'briefcase',
  dot: DOT,
};
const ROSE: Palette = {
  icon: 'handshake',
  dot: DOT,
};
const VIOLET: Palette = {
  icon: 'code',
  dot: DOT,
};
const TEAL: Palette = {
  icon: 'landmark',
  dot: DOT,
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
  // One step lighter than a tagged category's `--subtle` marker, so an untagged card reads as
  // quieter rather than as a different kind of thing. Was #A1A1AA, off-token like the rest.
  dot: 'bg-border-strong',
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
