/**
 * What the shelf actually costs, computed from the shelf.
 *
 * WHY THIS EXISTS
 *
 * Until the segment price ladder shipped (`feat(pricing)` #105/#107), every pack was £49 and the
 * storefront said so in twelve hardcoded places: the `<title>` suffix, the default meta
 * description, the footer tagline, the trust row, three hero paragraphs, the FAQ answer, and a
 * whole `/pricing` page headed "One price, every pack."
 *
 * Measured against the live catalogue on 2026-08-05
 * (`curl -s https://api.mumchimp.com/catalog`):
 *
 *     61 packs -- £29 x5, £49 x48, £79 x5, £99 x1, £149 x1, £199 x1
 *
 * So "£49 each" was false for 13 of 61 packs (21%), and false on the pages a buyer reads BEFORE
 * they see a price tag. Two of those places are search-engine surfaces that stay cached for
 * months, which is the worst place for a stale price: the buyer arrives already told a number.
 *
 * THE RULE THIS ENCODES
 *
 * A price claim about the catalogue is derived from the catalogue or it is not made. Nothing here
 * is a constant; every figure below comes from the `Pack[]` the caller already fetched, so the
 * next ladder change updates the copy without a deploy. Where a surface has no catalogue to hand
 * (the static `<Seo>` defaults, the footer), the correct edit was to delete the number, not to
 * hardcode a newer one.
 */

/** Parse the catalogue's display price ("£49.00") to a number. Mirrors `fx.ts::parseGbp`. */
function gbp(price: string): number {
  return parseFloat(price.replace(/[^0-9.]/g, ''));
}

/** Whole pounds when the amount is whole, two decimals otherwise. "£49", "£49.50". */
export function formatGbp(amount: number): string {
  return `£${Number.isInteger(amount) ? amount : amount.toFixed(2)}`;
}

export interface PriceRange {
  /** Cheapest pack on the shelf, in pounds. */
  min: number;
  /** Dearest pack on the shelf, in pounds. */
  max: number;
  /** The price the largest number of packs share. */
  mode: number;
  /** How many packs are at `mode`. */
  modeCount: number;
  /** How many packs the range was computed from. */
  total: number;
  /** True when every pack is the same price, which is what the copy used to assume. */
  uniform: boolean;
  /** Buyer-facing summary: "£49" when uniform, otherwise "£29 to £199". */
  label: string;
  /** Buyer-facing lead-in for a headline: "£49 a pack." / "From £29 a pack." */
  headline: string;
}

/**
 * Returns null for an empty or unparseable catalogue. Callers must render no price claim at all
 * in that case -- a shelf we cannot read the prices of is not a shelf we can quote a price for.
 */
export function priceRange(packs: { price?: string | null }[]): PriceRange | null {
  const amounts = packs
    .map((p) => gbp(p.price ?? ''))
    .filter((n) => Number.isFinite(n) && n > 0);
  if (amounts.length === 0) return null;

  const counts = new Map<number, number>();
  for (const a of amounts) counts.set(a, (counts.get(a) ?? 0) + 1);

  let mode = amounts[0];
  let modeCount = 0;
  for (const [amount, count] of counts) {
    // Ties break to the cheaper price: it is the one a buyer can act on without being upsold.
    if (count > modeCount || (count === modeCount && amount < mode)) {
      mode = amount;
      modeCount = count;
    }
  }

  const min = Math.min(...amounts);
  const max = Math.max(...amounts);
  const uniform = min === max;

  return {
    min,
    max,
    mode,
    modeCount,
    total: amounts.length,
    uniform,
    label: uniform ? formatGbp(min) : `${formatGbp(min)} to ${formatGbp(max)}`,
    headline: uniform ? `${formatGbp(min)} a pack.` : `From ${formatGbp(min)} a pack.`,
  };
}

/** One occupied rung of the ladder: a price, and how many packs sit on it. */
export interface LadderRung {
  amount: number;
  count: number;
}

/**
 * The rungs the shelf ACTUALLY occupies, cheapest first.
 *
 * The engine's ladder is declared in `config.yaml:925`
 * (`rungs: [1900, 2900, 4900, 7900, 9900, 14900, 19900]`, with `tier_rung_index` at `:943` mapping
 * side_hustle/smb/growth/venture onto it and `market_rung_offset` at `:955` adding one rung for a
 * US-market opportunity). That list is NOT what this returns, for the reason this whole module
 * exists: config.yaml is not deployed with the storefront, and a page drawing seven rungs when the
 * catalogue only sells on four would be illustrating a hypothesis while claiming to show a shelf.
 * Config declares what prices are POSSIBLE; the catalogue is what is true.
 *
 * So an empty rung is simply absent. A visitor comparing this drawing against the catalogue finds
 * every rung on it, at the count stated, which is the only property that matters on a page whose
 * subject is "why does this cost what it costs".
 */
export function priceLadder(packs: { price?: string | null }[]): LadderRung[] {
  const counts = new Map<number, number>();
  for (const pack of packs) {
    const amount = gbp(pack.price ?? '');
    if (!Number.isFinite(amount) || amount <= 0) continue;
    counts.set(amount, (counts.get(amount) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([amount, count]) => ({ amount, count }))
    .sort((a, b) => a.amount - b.amount);
}

/**
 * The one-sentence honest description of the ladder, e.g.
 * "Most packs are £49. They run £29 to £199, priced per pack -- the price is on every pack page."
 *
 * Deliberately states the mode AND the spread. Quoting only "from £29" when 48 of 61 packs are
 * £49 is the airline-fare move: technically true, and the buyer discovers the real number after
 * they have committed attention.
 */
export function priceSentence(range: PriceRange): string {
  if (range.uniform) {
    return `Every pack is ${formatGbp(range.min)}. One payment, no subscription, no upsell.`;
  }
  return (
    `${range.modeCount} of the ${range.total} packs on the shelf are ${formatGbp(range.mode)}. ` +
    `They run ${range.label}, priced per pack, and the price is on the pack's own page. ` +
    // A colon, not `--` and not a dash. There is no markdown parser between here and the DOM,
    // so `--` printed literally on /pricing as two hyphens (desktop-pricing-fold.png,
    // 2026-08-06). The obvious repair, an en dash, is banned by `dashFree.test.ts`: em/en
    // dashes are the most recognisable AI-writing signature and this is a storefront pitching
    // source-or-die. Punctuation that is neither is the answer, so the clause takes a colon.
    `Whichever you pick, it is one payment: no subscription, no upsell.`
  );
}
