import React from 'react';
import { cx } from './cx';

export interface MoneyProps {
  /** Amount in MINOR units (e.g. `escrow_amount_cents`). This component never does math beyond /100. */
  cents: number;
  /** ISO 4217 code, e.g. `USD`, `GBP`, `EUR`. Comes straight from the API field. */
  currency: string;
  className?: string;
}

/** A `.` or `,` sitting BETWEEN two digits: a decimal point or a thousands mark, never a full stop. */
const GROUP_SEPARATOR = /(?<=\d)([.,])(?=\d)/g;

/**
 * Sets the separators inside a formatted number tight.
 *
 * WHY THIS EXISTS. The house style sets every checkable quantity in monospace (`tokens.css`: "the
 * reader learns that monospace means you can verify this"), and a price is the most checkable
 * quantity on the site. But in a monospace face every glyph takes the same advance, so a full stop
 * -- roughly 0.1em of ink -- is given a ~0.6em cell, and at display sizes the gap on each side of
 * it is wider than the space between words. Measured on the rendered shelf at 390px on 2026-08-13
 * the pack cards read `£149 . 99` and the population field's total read `1 , 444`: three tokens,
 * not one number. `tracking-tight` was already on the price span and did not fix it -- at -0.025em
 * it removes about half a pixel per character, against a gap of eight.
 *
 * So the fix is applied where the defect is, on the separator alone: a negative margin either side
 * pulls the following digits back and leaves every DIGIT's advance untouched. That last part is
 * what keeps `tabular-nums` meaningful -- the shelf's prices still align down a column, because two
 * numbers with the same shape are narrowed by the same fixed amount.
 *
 * The lookarounds are the whole safety argument: only a separator with a digit on BOTH sides is
 * touched, so a full stop ending a sentence, a decimal comma in prose and a trailing `1.` are all
 * left exactly as they were. A string with no such separator (`£49`) is returned unchanged, as the
 * string it already was.
 */
export function tightDecimal(formatted: string): React.ReactNode {
  const parts = formatted.split(GROUP_SEPARATOR);
  if (parts.length === 1) return formatted;
  // `split` with one capture group yields [text, sep, text, sep, text, ...] -- odd indexes are the
  // separators, and those are the only spans that get the negative margin.
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} className="mx-[-0.17em]">
            {part}
          </span>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        ),
      )}
    </>
  );
}

/** The leading currency run: everything before the first digit. `£`, `$`, `US$`, `€`. */
// No `s` flag: the tsconfig target predates it, and a formatted price is a single line anyway --
// anything containing a newline simply falls through to `tightDecimal` unchanged.
const LEADING_SYMBOL = /^([^\d]+)(.*)$/;

/**
 * Sets the currency symbol at 0.8em (founder directive, 2026-08-15).
 *
 * The directive it belongs to is "prices come OFF blue": a blue price is a broken affordance --
 * a reader who has learned that blue means "tap this" taps £49.99 and nothing happens. But a
 * price that is simply ink like everything else around it stops being findable, which is the
 * problem the blue was added to solve. So the price is differentiated from the button by WEIGHT
 * and SIZE instead of by hue, and this is the size half: the figure keeps its full cap height and
 * the symbol steps back, which is how a price list has been set since long before the web.
 *
 * It is applied HERE rather than at the five call sites for the reason this file already exists:
 * `Money` and `PriceText` are the only two ways money reaches a reader, so one edit is the whole
 * population. A per-call-site class is how the last repaint reached three of four shelf cards.
 *
 * `em`, not a token: the symbol must track whatever type scale the caller chose, from the shelf
 * card's `text-caption` to the hero's `text-h1`.
 */
function withSmallSymbol(formatted: string): React.ReactNode {
  const m = LEADING_SYMBOL.exec(formatted);
  if (!m) return tightDecimal(formatted);
  const [, symbol, rest] = m;
  return (
    <>
      {/* Not aria-hidden: the symbol is the only thing saying which currency this is. */}
      <span className="cur text-[0.8em]">{symbol}</span>
      {tightDecimal(rest)}
    </>
  );
}

/**
 * Renders a minor-unit money amount. The ONLY way money is shown (UI-STANDARDS §2).
 * Fixed locale so server and client render byte-identical (no hydration drift).
 */
export function Money({ cents, currency, className }: MoneyProps) {
  const formatted = new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency,
  }).format(cents / 100);
  return (
    <span className={cx('font-mono font-semibold tabular-nums', className)}>
      {withSmallSymbol(formatted)}
    </span>
  );
}

export interface PriceTextProps {
  /**
   * An ALREADY-FORMATTED price, as the catalogue carries it (`pack.price`, `formatGbp(...)`). This
   * component formats nothing and converts nothing -- the money rail owns that, and a second
   * formatter on the display side is how a catalogue row and a Stripe charge start to disagree.
   */
  children: string;
  className?: string;
}

/**
 * A formatted price string, set in the house mono voice with the decimal separator closed up and
 * the currency symbol at 0.8em.
 *
 * `font-semibold` is baked in here rather than repeated at every call site: under the 2026-08-15
 * colour directive the price is INK like the prose around it, so weight is now the only thing
 * making it findable, and a call site that forgot the class would render a price that reads as
 * body copy. Hue is not available for this job any more -- blue means "do something", and a price
 * does nothing.
 */
export function PriceText({ children, className }: PriceTextProps) {
  return (
    <span className={cx('font-mono font-semibold tabular-nums text-text', className)}>
      {withSmallSymbol(children)}
    </span>
  );
}
