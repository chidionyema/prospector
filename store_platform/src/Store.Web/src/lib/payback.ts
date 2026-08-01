import type { FinancialSnapshot } from '@/lib/api/client';

/**
 * The pack price against the economics the engine already modelled.
 *
 * This adds NO new engine field and invents NO number. Every value below is either the price
 * the buyer is about to pay or a figure already present in `financialSnapshot`, which the
 * engine computes in Python from the pack's verified inputs (`prospector/artifacts.py`,
 * `_financial_snapshot`). The only new thing on the page is the division, and it is shown.
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
  /** revenue / price, rounded down. Only ever >= 1 (see `paybackEquation`). */
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
 * Build the equation, or return null so the page renders nothing.
 *
 * Returns null, rather than a weaker version, whenever the comparison would not be honest:
 * no modelled revenue, an unparseable or ranged figure, or a modelled month-1 revenue that
 * does not even cover the pack price. That last case is the important one: this must not
 * become a widget that only ever appears when it flatters the sale. If the modelled economics
 * do not clear £49, the buyer reads the "Modelled economics" box further down and judges for
 * themselves; the storefront does not get to reframe it into a multiple below 1.
 */
export function paybackEquation(price: string, snapshot?: FinancialSnapshot): Payback | null {
  if (!snapshot) return null;

  const priceValue = parsePrice(price);
  const revenueValue = parseAmount(snapshot.month1Revenue);
  if (priceValue === null || revenueValue === null) return null;

  const multiple = Math.floor(revenueValue / priceValue);
  if (multiple < 1) return null;

  return {
    priceLabel: price.replace(/[.,]00\b/, ''),
    revenueLabel: snapshot.month1Revenue!.trim(),
    multiple,
    paybackMonths: snapshot.paybackMonths?.trim() || null,
  };
}
