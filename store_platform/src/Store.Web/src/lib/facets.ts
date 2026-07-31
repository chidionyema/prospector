/**
 * The discovery facet vocabulary — the TypeScript end of one closed contract.
 *
 * The same six vocabularies exist in Python at `prospector/facets.py` and in C# at
 * `store_platform/src/Store.Catalog/Domain/PackFacets.cs`. Three copies is a deliberate cost:
 * the engine, the API and the browser are three deploy units, and a shared runtime dependency
 * between them would be a worse coupling than three lists a test can compare. The test that
 * makes the cost safe is `src/lib/__tests__/facets.test.ts`, which reads `PackFacets.cs` off
 * disk and asserts value-for-value equality — so a facet added in one language and forgotten
 * in another fails `npm test` rather than silently disappearing from the filter bar.
 *
 * Two rules this module exists to enforce:
 *
 * 1. **No facet is ever inferred from pack text.** The storefront guessed sector with a regex
 *    over title + one-liner and told buyers a metal-fabrication quoting engine was a gardening
 *    business (`src/lib/category.ts`, deleted by this story). On a brand whose whole position
 *    is "every claim sourced", a filter that lies is worse than no filter.
 * 2. **Absent means absent.** An untagged pack renders no chip and appears only under "All".
 *    There is no default value anywhere in this file, and `label()` returns null for an
 *    unknown code rather than prettifying it — a rendered guess is a claim nobody made.
 */

export const ADVANTAGE = ['code', 'nocode', 'sales', 'ops', 'audience'] as const;
export const PAYER = ['b2b', 'b2c', 'b2g'] as const;
export const EFFORT = ['automatable', 'part_automatable', 'hands_on'] as const;
export const COMMITMENT = ['evenings', 'part_time', 'full_time'] as const;
export const MECHANISM = [
  'productized_service',
  'vertical_tool',
  'transaction_broker',
  'risk_financing',
  'physical_ops',
  'audience_media',
  'picks_and_shovels',
  'data_intelligence',
] as const;
export const SECTOR = [
  'licensing_admin',
  'employment_pay',
  'housing_rental',
  'care_benefits',
  'trades_construction',
  'pets_animals',
  'creative_rights',
  'property_probate',
  'energy_planning',
  'retail_inventory',
  'professional_services',
  'other',
] as const;

export type Advantage = (typeof ADVANTAGE)[number];
export type Payer = (typeof PAYER)[number];
export type Effort = (typeof EFFORT)[number];
export type Commitment = (typeof COMMITMENT)[number];
export type Mechanism = (typeof MECHANISM)[number];
export type Sector = (typeof SECTOR)[number];

/** A pack carries at most three advantages (`prospector/facets.py` MAX_ADVANTAGES). */
export const MAX_ADVANTAGES = 3;

/** Every facet except `advantage` holds one value or none. */
export const SINGLE_VALUED_KINDS = ['sector', 'payer', 'effort', 'commitment', 'mechanism'] as const;
export type SingleValuedKind = (typeof SINGLE_VALUED_KINDS)[number];
export type FacetKind = SingleValuedKind | 'advantage';

export const VOCABULARY: Record<FacetKind, readonly string[]> = {
  advantage: ADVANTAGE,
  sector: SECTOR,
  payer: PAYER,
  effort: EFFORT,
  commitment: COMMITMENT,
  mechanism: MECHANISM,
};

/** True when `value` is a member of that facet's closed vocabulary. Null/undefined are false. */
export function isFacetValue(kind: FacetKind, value: string | null | undefined): boolean {
  if (!value) return false;
  return VOCABULARY[kind].includes(value);
}

/**
 * Display copy. Chips must read as English — the old card rendered `{effortTag} effort`, giving
 * buyers "Highly automatable effort" (spec Part 10). Every string here is buyer-facing and this
 * file is its only home, so a wording change happens in one place rather than five components.
 */
const LABELS: Record<FacetKind, Record<string, string>> = {
  advantage: {
    code: 'Suits builders',
    nocode: 'No code needed',
    sales: 'Suits sellers',
    ops: 'Suits operators',
    audience: 'Suits an audience',
  },
  payer: {
    b2b: 'Sells to businesses',
    b2c: 'Sells to consumers',
    b2g: 'Sells to public bodies',
  },
  effort: {
    automatable: 'Mostly automated',
    part_automatable: 'Part automated',
    hands_on: 'Hands-on service',
  },
  commitment: {
    evenings: 'Evenings-friendly',
    part_time: 'Part-time hours',
    full_time: 'Full-time',
  },
  mechanism: {
    productized_service: 'Productised service',
    vertical_tool: 'Vertical tool',
    transaction_broker: 'Transaction broker',
    risk_financing: 'Risk and financing',
    physical_ops: 'Physical operations',
    audience_media: 'Audience and media',
    picks_and_shovels: 'Picks and shovels',
    data_intelligence: 'Data intelligence',
  },
  sector: {
    licensing_admin: 'Licensing and admin',
    employment_pay: 'Employment and pay',
    housing_rental: 'Housing and rental',
    care_benefits: 'Care and benefits',
    trades_construction: 'Trades and construction',
    pets_animals: 'Pets and animals',
    creative_rights: 'Creative rights',
    property_probate: 'Property and probate',
    energy_planning: 'Energy and planning',
    retail_inventory: 'Retail and inventory',
    professional_services: 'Professional services',
    other: 'Other',
  },
};

/**
 * Compact copy for dense rows — the command palette shows four facts plus a price on one line
 * (spec :274), where "Sells to consumers" pushes the price off a phone. Only defined where it
 * differs from the full label; `shortLabel` falls back to `label` otherwise.
 */
const SHORT_LABELS: Partial<Record<FacetKind, Record<string, string>>> = {
  payer: { b2b: 'B2B', b2c: 'B2C', b2g: 'B2G' },
  advantage: {
    code: 'Builders',
    nocode: 'No code',
    sales: 'Sellers',
    ops: 'Operators',
    audience: 'Audience',
  },
};

/**
 * Buyer-facing text for one facet value, or null when the value is absent or outside the
 * vocabulary. Null is deliberate: an unrecognised code means the API is ahead of this deploy,
 * and rendering the raw token ("part_automatable") or a prettified guess would both be worse
 * than rendering nothing.
 */
export function label(kind: FacetKind, value: string | null | undefined): string | null {
  if (!value) return null;
  return LABELS[kind][value] ?? null;
}

/** As `label`, but the compact form where one exists. Same null contract. */
export function shortLabel(kind: FacetKind, value: string | null | undefined): string | null {
  if (!value) return null;
  return SHORT_LABELS[kind]?.[value] ?? label(kind, value);
}

/** Heading copy for a facet's group in the filter bar. */
export const KIND_LABEL: Record<FacetKind, string> = {
  advantage: 'What you already have',
  payer: 'Who pays',
  effort: 'How much is automated',
  commitment: 'Time it needs',
  mechanism: 'How it makes money',
  sector: 'Sector',
};
