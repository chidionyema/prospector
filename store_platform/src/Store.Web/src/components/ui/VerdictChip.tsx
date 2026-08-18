import React from 'react';
import { Glyph, type GlyphName } from './Glyph';
import { cx } from './cx';

/**
 * The three verdicts, drawn one way, in one place (MASTER-BRIEF §6).
 *
 * WHY THIS EXISTS
 * ---------------
 * The brief's rule is one line: "survived / pushed-back / killed. The only place `--kill` may
 * appear." It exists because the site kept spending red on things that were not kills. Measured
 * 2026-08-17, before this component:
 *
 *   CheckSequence.tsx:101   a pushed-back check's numeral drawn `border-kill bg-kill-bg`
 *   CheckSequence.tsx:139   the word "pushed back" drawn `text-kill`
 *   CheckSequence.tsx:178   the summary count "N pushed back" drawn `text-kill`
 *   HeroEvidenceStrip.tsx   the same three states, drawn correctly, in amber
 *
 * So the homepage carried two colour families for one state, two components apart. Red is the
 * signal the kill log depends on, and a shop that spends it on a non-fatal check has spent it.
 * Each of those sites was fixed by hand at least twice before; hand-fixing does not hold, because
 * the next component to render a verdict starts from a blank className.
 *
 * COLOUR IS NEVER THE SOLE CARRIER. Every chip renders a `Glyph`, and the glyphs differ by SHAPE
 * (filled, half-filled, crossed), plus the verdict WORD in text. The set survives being printed in
 * one ink, which is what a colour-blind reader gets.
 *
 * The ratios, measured on the MASTER-BRIEF §1 palette:
 *   survived     --survive #14706A            5.91:1 on white
 *   pushed back  --pushed-back-strong #6E5608 6.70:1 on --bg, 6.58:1 on its own tint
 *   killed       --kill #B4342B               6.06:1 on white
 */

export type VerdictKind = 'survived' | 'pushed-back' | 'killed';

const GLYPH_FOR: Record<VerdictKind, GlyphName> = {
  survived: 'survived',
  'pushed-back': 'pushed-back',
  killed: 'killed',
};

/** The word a reader sees. Sentence case, because it sits inside running text as often as not. */
const WORD_FOR: Record<VerdictKind, string> = {
  survived: 'survived',
  'pushed-back': 'pushed back',
  killed: 'killed',
};

/**
 * THE DRAWING'S OWN VERDICT TAG (`mockups/how-it-works.html:71-74`):
 *
 *   .v{display:inline-flex;gap:6px;font-family:var(--font-mono);font-size:11px;
 *      letter-spacing:.08em;text-transform:uppercase;border:1px solid;border-radius:4px;padding:3px 8px}
 *   .v.s{border-color:var(--brand);color:var(--brand);background:var(--brand-tint)}
 *   .v.p{border-color:var(--warn-b);color:var(--warn-t);background:var(--warn-f)}
 *   .v.k{border-color:var(--kill);color:var(--kill)}
 *
 * Every mockup that shows a verdict draws this tag: eleven of them on `/how-it-works`, eight on
 * `/kill-log`. We drew the same three states in Tailwind utilities instead, so none of those pages
 * emitted the class the drawings style, and the two could drift with nothing to catch it.
 *
 * The utilities are REMOVED rather than layered. `mockup.css` is imported into
 * `layer(components)` (globals.css:8) and Tailwind utilities sit above it, so any utility left in
 * place would beat the class and this change would draw nothing.
 *
 * COLOUR IS STILL NEVER THE SOLE CARRIER: each chip keeps its `Glyph`, and the glyphs differ by
 * shape, plus the verdict word in text.
 */
const KIND_CLASS: Record<VerdictKind, string> = {
  survived: 's',
  'pushed-back': 'p',
  killed: 'k',
};

export interface VerdictChipProps {
  kind: VerdictKind;
  /**
   * Replaces the verdict word. For a count ("3 pushed back") or a gate's own phrasing. The chip
   * still draws the glyph, so the meaning does not rest on the caller's wording.
   */
  label?: React.ReactNode;
  className?: string;
}

export function VerdictChip({ kind, label, className }: VerdictChipProps) {
  return (
    <span data-verdict={kind} className={cx('v', KIND_CLASS[kind], className)}>
      <Glyph name={GLYPH_FOR[kind]} />
      {label ?? WORD_FOR[kind]}
    </span>
  );
}

export default VerdictChip;
