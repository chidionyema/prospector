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
 * Ink only, for a chip sitting on the page ground.
 *
 * `--kill` appears HERE and, per the brief, nowhere else. `--pushed-back-strong` rather than
 * `--pushed-back`: the base amber is 4.70:1 on `--bg` and the strong is 6.70:1, and this text is
 * caption-sized, which is exactly where the extra headroom is worth having.
 */
const INK_FOR: Record<VerdictKind, string> = {
  survived: 'text-survive',
  'pushed-back': 'text-pushed-back-strong',
  killed: 'text-kill',
};

/** Tint ground plus an edge, for a chip that has to hold its own against a busy row. */
const SOLID_FOR: Record<VerdictKind, string> = {
  survived: 'border border-survive bg-survive-bg text-survive-strong',
  'pushed-back': 'border border-pushed-back bg-pushed-back-bg text-pushed-back-strong',
  killed: 'border border-kill bg-kill-bg text-kill-strong',
};

export interface VerdictChipProps {
  kind: VerdictKind;
  /**
   * Replaces the verdict word. For a count ("3 pushed back") or a gate's own phrasing. The chip
   * still draws the glyph, so the meaning does not rest on the caller's wording.
   */
  label?: React.ReactNode;
  /** `tint` draws a ground and an edge; `ink` is the word alone. Default `ink`. */
  variant?: 'ink' | 'tint';
  className?: string;
}

export function VerdictChip({ kind, label, variant = 'ink', className }: VerdictChipProps) {
  return (
    <span
      data-verdict={kind}
      className={cx(
        'inline-flex items-center gap-1.5 font-mono text-caption leading-none',
        variant === 'tint' ? cx('rounded-ctl px-2 py-1', SOLID_FOR[kind]) : INK_FOR[kind],
        className,
      )}
    >
      <Glyph name={GLYPH_FOR[kind]} />
      {label ?? WORD_FOR[kind]}
    </span>
  );
}

export default VerdictChip;
