/**
 * Presentation for the engine's `sector` facet: a colour, a gradient and an icon per sector.
 *
 * This file used to infer the sector with six regexes over the pack's title and one-liner. That
 * is deleted (spec Part 10, AC-5) and must not come back. The regex table told buyers a metal
 * fabrication quoting engine was a gardening business, and on a storefront whose whole position
 * is "every claim has a clickable source", a category the browser invented is a claim with no
 * source behind it.
 *
 * The rule now: `sector` comes from the API or the pack has no category. An untagged pack gets
 * the neutral `unlabelled` treatment — honest, and visibly different from a real sector.
 *
 * Class strings are FULL LITERALS (gradient + tint) so Tailwind keeps them at build time; never
 * interpolate them.
 */
import type { IconName } from '@/components/ui/Icon';
import { SECTOR, label as facetLabel, type Sector } from '@/lib/facets';

export interface Category {
  /** The engine's sector code, or `unlabelled` when the pack carries no sector. */
  key: string;
  label: string;
  icon: IconName;
  /** Full-height card cover gradient. */
  cover: string;
  /** Label-pill tint (bg + text + inset ring), reads on white. */
  chip: string;
  /** Small accent text colour. */
  accent: string;
}

type Palette = Pick<Category, 'icon' | 'cover' | 'chip' | 'accent'>;

const INDIGO: Palette = {
  icon: 'gavel',
  cover: 'bg-[linear-gradient(135deg,#4f46e5_0%,#7c3aed_100%)]',
  chip: 'bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-600/20',
  accent: 'text-indigo-600',
};
const EMERALD: Palette = {
  icon: 'home',
  cover: 'bg-[linear-gradient(135deg,#0d9488_0%,#059669_100%)]',
  chip: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20',
  accent: 'text-emerald-700',
};
const AMBER: Palette = {
  icon: 'building',
  cover: 'bg-[linear-gradient(135deg,#d97706_0%,#ea580c_100%)]',
  chip: 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-600/20',
  accent: 'text-amber-700',
};
const SKY: Palette = {
  icon: 'wallet',
  cover: 'bg-[linear-gradient(135deg,#2563eb_0%,#0284c7_100%)]',
  chip: 'bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-600/20',
  accent: 'text-sky-600',
};
const SLATE: Palette = {
  icon: 'briefcase',
  cover: 'bg-[linear-gradient(135deg,#334155_0%,#4338ca_100%)]',
  chip: 'bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-500/20',
  accent: 'text-slate-600',
};
const ROSE: Palette = {
  icon: 'handshake',
  cover: 'bg-[linear-gradient(135deg,#be123c_0%,#db2777_100%)]',
  chip: 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-600/20',
  accent: 'text-rose-600',
};
const VIOLET: Palette = {
  icon: 'code',
  cover: 'bg-[linear-gradient(135deg,#6d28d9_0%,#9333ea_100%)]',
  chip: 'bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-600/20',
  accent: 'text-violet-600',
};
const TEAL: Palette = {
  icon: 'landmark',
  cover: 'bg-[linear-gradient(135deg,#0f766e_0%,#0891b2_100%)]',
  chip: 'bg-teal-50 text-teal-700 ring-1 ring-inset ring-teal-600/20',
  accent: 'text-teal-700',
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
 * The untagged treatment. Named "Not yet tagged" rather than given a plausible-sounding label,
 * because "Opportunity" reads like a category the engine assigned when it is really the absence
 * of one.
 */
export const UNLABELLED: Category = {
  key: 'unlabelled',
  label: 'Not yet tagged',
  icon: 'briefcase',
  cover: 'bg-[linear-gradient(135deg,#0f172a_0%,#334155_100%)]',
  chip: 'bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-500/20',
  accent: 'text-slate-500',
};

const CATEGORIES: Record<string, Category> = Object.fromEntries(
  SECTOR.map((sector) => [
    sector,
    { key: sector, label: facetLabel('sector', sector) ?? sector, ...PALETTE[sector] },
  ]),
);

/**
 * The category for a pack, read from the engine's `sector` and nothing else. A pack with no
 * sector — or with one this build does not know — gets `UNLABELLED`. No pack text is inspected.
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
