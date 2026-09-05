import type { FinancialSnapshot } from '@/lib/api/client';

/**
 * The pack price against the economics the engine already modelled.
 *
 * This adds NO new engine field and invents NO number. Every value below is either the price
 * the buyer is about to pay or a figure already present in `financialSnapshot`, which the
 * engine computes in Python from the pack's stated assumptions (`prospector/artifacts.py`,
 * `_financial_snapshot`). NOT "verified inputs": `_render_financial_model` (artifacts.py:152)
 * receives the `claims` list and never reads it, so no input here carries a citation. The
 * arithmetic is exact; the assumptions are assumptions. The only new thing on the page is the
 * division, and it is shown.
 *
 * It exists because "£49" sitting alone next to a buy button is a cost with nothing to weigh it
 * against, while the numbers that would answer "is this worth £49?" were already on the page,
 * 400px further down, in a box labelled "Modelled economics".
 */
export interface Payback {
  /** The price, formatted as it appears on the button. */
  priceLabel: string;
  /** The modelled month-1 revenue, exactly as the engine wrote it. */
  revenueLabel: string;
  /** revenue / price, rounded down. Only ever 1..`CREDIBLE_MULTIPLE_CEILING` (see
   *  `paybackEquation`) -- bounded at both ends, for opposite reasons. */
  multiple: number;
  /** Modelled payback period, when the engine stated one. Never derived. */
  paybackMonths: string | null;
}

/** Numbers in the snapshot are prose ("£2,400", "$1.2k/mo", "3.4x"). Pull the leading amount,
 *  honouring a `k`/`m` suffix. Returns null when there is no unambiguous number to read, a
 *  range ("£500 to £2,000") is deliberately refused rather than half-read. */
export function parseAmount(raw: string | undefined): number | null {
  if (typeof raw !== 'string') return null;
  const text = raw.trim();
  if (!text) return null;

  // A range has two numbers and no single honest answer. Bail rather than pick one.
  const numbers = text.match(/\d[\d,]*(?:\.\d+)?/g) ?? [];
  if (numbers.length !== 1) return null;

  const value = parseFloat(numbers[0].replace(/,/g, ''));
  if (!Number.isFinite(value) || value <= 0) return null;

  // Suffix immediately after the number only, so "2k" scales but "£2,400 in month 1000" does not
  // accidentally match a stray letter elsewhere in the sentence.
  const after = text.slice(text.indexOf(numbers[0]) + numbers[0].length);
  const suffix = /^\s*([km])\b/i.exec(after)?.[1]?.toLowerCase();
  if (suffix === 'k') return value * 1_000;
  if (suffix === 'm') return value * 1_000_000;
  return value;
}

/** The price string is "£49.00" / "49.00", the same money the buy button charges. */
function parsePrice(price: string): number | null {
  const value = parseFloat(price.replace(/[^\d.]/g, ''));
  return Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * The largest multiple this shop will state, anywhere.
 *
 * Founder, 2026-08-15, on seeing 123x on the live shelf: "123x is the number that makes a buyer
 * distrust the other 58 cards. exactly." The argument is about the reader, not the arithmetic --
 * the division is exact, and a claim that a pack returns 123 times its price inside thirty days
 * is still read as a lie, which then retroactively prices every honest 6x beside it as marketing.
 * An implausible number is not a strong claim; it is a solvent applied to the credible ones.
 *
 * Set at 20 because the live distribution and the plausibility argument break in the same place.
 * Measured over all 59 listed packs (2026-08-15), the 36 renderable multiples were
 *   2 2 3 3 4 5 6 6 6 6 7 7 7 8 8 9 9 9 9 10 12 12 13 13 14 16 17 17 | 21 22 25 30 45 76 89 123
 * -- the body ends at 17x (28 of 36, p75 = 17) and the rest is a tail, not a continuation. And
 * 20x of a 49.99 pack is a modelled £1,000 in month one, the top of what a person starting from
 * nothing reads as possible; above it the claim runs to £6,150 and stops being arguable.
 *
 * It lives HERE rather than at a render site because the founder's answer to "apply it to the
 * detail page too?" was yes: one rule, one place, both readers. A ceiling enforced per-caller is
 * a ceiling the next caller forgets.
 */
export const CREDIBLE_MULTIPLE_CEILING = 20;

/**
 * Build the equation, or return null so the page renders nothing.
 *
 * Returns null, rather than a weaker version, whenever the comparison would not be honest:
 * no modelled revenue, an unparseable or ranged figure, a modelled month-1 revenue that does not
 * even cover the pack price, or one so far above it that stating it costs more credibility than
 * it buys. The bottom case is what stops this becoming a widget that only appears when it
 * flatters the sale; the top case is what stops it flattering so hard nobody believes the shelf.
 * Either way the buyer reads the "Modelled economics" box further down and judges for themselves;
 * the storefront does not get to reframe those numbers into a multiple it cannot defend.
 *
 * Null and not a clamp, deliberately: "20x+" makes the same claim less precisely and invites the
 * reader to wonder what was capped.
 */
export function paybackEquation(price: string, snapshot?: FinancialSnapshot): Payback | null {
  if (!snapshot) return null;

  const priceValue = parsePrice(price);
  const revenueValue = parseAmount(snapshot.month1Revenue);
  if (priceValue === null || revenueValue === null) return null;

  const multiple = Math.floor(revenueValue / priceValue);
  if (multiple < 1 || multiple > CREDIBLE_MULTIPLE_CEILING) return null;

  return {
    priceLabel: price.replace(/[.,]00\b/, ''),
    revenueLabel: snapshot.month1Revenue!.trim(),
    multiple,
    paybackMonths: snapshot.paybackMonths?.trim() || null,
  };
}


/** Months from the engine string ("8.1 months", "3 months"). Null if unreadable. */
export function parsePaybackMonths(raw: string | null | undefined): number | null {
  if (!raw) return null;
  const m = /(\d+(?:\.\d+)?)\s*month/i.exec(raw);
  if (!m) return null;
  const n = parseFloat(m[1]);
  return Number.isFinite(n) ? n : null;
}

/**
 * One label, from the model. Months win when the engine stated them.
 * Cards suppress ≤ 1× and > 18 months (brief §4.2, 2026-09-02).
 */
export function paybackLabel(eq: Payback | null, surface: "card" | "page" = "page"): string | null {
  if (!eq) return null;
  const months = parsePaybackMonths(eq.paybackMonths);
  if (months != null) {
    if (surface === "card" && months > 18) return null;
    const rounded = Math.round(months);
    return `Pays back in ${rounded} month${rounded === 1 ? "" : "s"}.`;
  }
  if (surface === "card" && eq.multiple <= 1) return null;
  return `${eq.multiple}× first-year return.`;
}
