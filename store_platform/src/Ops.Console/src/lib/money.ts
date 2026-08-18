/**
 * Money rendering, and the one arithmetic rule the shop has.
 *
 * Every amount the store records is in MINOR UNITS (pence, cents) and carries its own currency.
 * Two rules follow, and both are enforced here rather than left to each page:
 *
 *   - CURRENCIES ARE NEVER COMBINED. There is no such thing as "total revenue" in a shop that
 *     sells in more than one currency. £40 plus $40 is not 80 of anything. `addMinorUnits` THROWS
 *     when handed two currencies instead of quietly returning a number that means nothing, and
 *     `perCurrency` is the only way to reduce a mixed list — it returns one figure per currency,
 *     so a screen showing two currencies shows two lines.
 *   - A MISSING AMOUNT IS NOT ZERO. `money(null, 'GBP')` is the words "not recorded", never
 *     "£0.00". A blank tile reads as "no sales" when it means "we could not measure", and that is
 *     the difference between a quiet day and a broken read.
 */
import { ABSENT } from '@/lib/time';

/** Symbols for the currencies this shop actually takes. Anything else prints its ISO code. */
const SYMBOLS: Record<string, string> = {
  GBP: '£',
  USD: '$',
  EUR: '€',
  CAD: 'CA$',
  AUD: 'A$',
  JPY: '¥',
};

/** Currencies whose "minor unit" is the unit. Dividing these by 100 invents two decimals. */
const ZERO_DECIMAL = new Set(['JPY', 'KRW', 'VND', 'CLP', 'ISK']);

export type MoneyRow = { currency: string | null; minorUnits: number | null };

export function currencyCode(currency: string | null | undefined): string | null {
  const c = (currency ?? '').trim().toUpperCase();
  return c === '' ? null : c;
}

/** `£` for GBP, `$` for USD, the ISO code plus a space for anything unmapped. */
export function symbolFor(currency: string | null | undefined): string {
  const c = currencyCode(currency);
  if (!c) return '';
  return SYMBOLS[c] ?? `${c} `;
}

/**
 * One amount, in its own currency. Absent renders as words.
 *
 * An amount with no currency is also absent: a bare number of pence with nothing saying which
 * pence is not a figure anyone can act on.
 */
export function money(
  minorUnits: number | null | undefined,
  currency: string | null | undefined,
): string {
  const c = currencyCode(currency);
  if (minorUnits === null || minorUnits === undefined || !Number.isFinite(minorUnits)) return ABSENT;
  if (!c) return ABSENT;
  if (ZERO_DECIMAL.has(c)) return `${symbolFor(c)}${Math.round(minorUnits).toLocaleString()}`;
  const major = minorUnits / 100;
  return `${symbolFor(c)}${major.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * Adds amounts that share ONE currency, and refuses anything else.
 *
 * The throw is the point. A silent sum across currencies is a number that looks like revenue,
 * gets read out loud, and is wrong by whatever the exchange rate happens to be.
 */
export function addMinorUnits(rows: MoneyRow[]): number | null {
  const currencies = new Set<string>();
  for (const r of rows) {
    const c = currencyCode(r.currency);
    if (c) currencies.add(c);
  }
  if (currencies.size > 1) {
    throw new Error(
      `refusing to add ${[...currencies].sort().join(' and ')} together: ` +
        'money in two currencies has no total. Use perCurrency.',
    );
  }
  // One unmeasured contributor makes the whole sum unmeasured. An under-count that renders as a
  // confident number is worse than an honest absence.
  let total = 0;
  for (const r of rows) {
    if (r.minorUnits === null || r.minorUnits === undefined || !Number.isFinite(r.minorUnits)) {
      return null;
    }
    total += r.minorUnits;
  }
  return total;
}

/**
 * One figure per currency, in a stable order. The only legal way to reduce a mixed list.
 *
 * A currency with any unmeasured contributor comes back with a null figure, so the screen says
 * "not recorded" for that line instead of showing a total that is quietly short.
 */
export function perCurrency(rows: MoneyRow[]): { currency: string; minorUnits: number | null }[] {
  const totals = new Map<string, number | null>();
  for (const r of rows) {
    const c = currencyCode(r.currency);
    if (!c) continue;
    const seen = totals.has(c) ? totals.get(c)! : 0;
    if (seen === null) continue;
    const v = r.minorUnits;
    totals.set(c, v === null || v === undefined || !Number.isFinite(v) ? null : seen + v);
  }
  return [...totals.entries()]
    .map(([currency, minorUnits]) => ({ currency, minorUnits }))
    .sort((a, b) => a.currency.localeCompare(b.currency));
}

/** Adds counts that are plain integers, keeping an absence absent. */
export function addCounts(values: (number | null | undefined)[]): number | null {
  let total = 0;
  for (const v of values) {
    if (v === null || v === undefined || !Number.isFinite(v)) return null;
    total += v;
  }
  return total;
}
