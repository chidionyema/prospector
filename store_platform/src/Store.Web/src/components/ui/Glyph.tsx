import { cx } from './cx';

/**
 * The verdict glyph set: spec §3.3, the entire icon vocabulary for ENGINE OUTPUT.
 *
 * Six marks, 14x14, 1.5px stroke, drawn in `currentColor` so the parent's verdict token supplies
 * the colour and this file never names one. That is the whole point of the constraint: a glyph
 * that hardcoded `--kill` could be rendered beside a survived verdict and nothing would stop it.
 *
 * SCOPE, decided 2026-08-08. §3.3 says six marks are the entire icon set with no libraries, but
 * `lucide-react` also draws UI CHROME here (menu, close, search, chevrons) that has no equivalent
 * among the six. Founder call: this sprite owns every mark that carries a RULING; lucide keeps the
 * chrome. So the rule is not "no icon library", it is the sharper one -- a verdict is never drawn
 * by a general-purpose icon set, and `components/ui/Icon.tsx` (lucide) is never used for one.
 *
 * WHY THESE ARE PATHS AND NOT A <symbol>/<use> SPRITE: a real sprite needs its <defs> mounted once
 * in the document, which on this Pages-router site means _document.tsx -- and a glyph would then
 * render as nothing on any surface that forgot to mount it, silently and only in production.
 * Inlining costs a few hundred bytes per instance after gzip and cannot fail that way.
 *
 * THE KNOCKOUT IS A MASK, NOT A BACKGROUND-COLOURED STROKE. "Filled square, ink tick knocked out"
 * has an obvious cheap implementation -- stroke the tick in `var(--bg)` -- which is wrong the
 * moment a survived glyph sits on anything other than the page canvas (it sits on --surface2 in
 * QA rows and on --survive-bg in the kill log). A mask makes the tick genuinely transparent, so
 * whatever is behind the glyph shows through and the mark is correct on every surface.
 *
 * COLOUR IS NEVER THE SOLE CARRIER (§3.1, and the acceptance checklist). These six differ by
 * SHAPE -- filled, half-filled, crossed, empty -- so the set survives being rendered in one ink,
 * which is exactly what happens when a reader is colour-blind or the page is printed. The
 * strikethrough that must accompany a killed row is the row's job, not the glyph's.
 */

export type GlyphName = 'survived' | 'pushed-back' | 'killed' | 'pending' | 'source';

/** The kill-log taxonomy codes (§3.3). Two mono letters, rendered beside the killed mark. */
export const KILL_CAUSE_CODES = {
  incumbency: 'IN',
  payer_solvency: 'PS',
  pain_reality: 'PA',
  distribution: 'DI',
  legality: 'LE',
  value_durability: 'VA',
} as const;

export type KillCause = keyof typeof KILL_CAUSE_CODES;

type GlyphProps = {
  name: GlyphName;
  className?: string;
  /**
   * Accessible name. Omitted by default: a glyph almost always sits beside the verdict word it
   * illustrates, and announcing "survived, survived" is worse than announcing it once. Pass a
   * label ONLY where the glyph is the sole carrier of the meaning.
   */
  label?: string;
};

// 1px corner radius on the glyph squares, per §3.4 ("--radius: 2px everywhere, glyph squares
// 1px"). The square is inset to 1.25 so the 1.5px stroke sits fully inside the 14x14 box rather
// than being clipped in half by the viewBox edge.
const BOX = { x: 1.25, y: 1.25, width: 11.5, height: 11.5, rx: 1 };

export function Glyph({ name, className, label }: GlyphProps) {
  const a11y = label
    ? { role: 'img' as const, 'aria-label': label }
    : { 'aria-hidden': true as const };

  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cx('inline-block flex-none align-[-0.15em]', className)}
      {...a11y}
    >
      {name === 'survived' && (
        <>
          {/* The mask is what knocks the tick out of the fill. `maskUnits="userSpaceOnUse"` because
              the default (objectBoundingBox) would scale the mask to the masked shape's bounds and
              put the tick somewhere other than where it is drawn. */}
          <mask id="glyph-survived" maskUnits="userSpaceOnUse" x="0" y="0" width="14" height="14">
            <rect {...BOX} fill="white" stroke="white" />
            <path d="M4.4 7.2 6.2 9l3.4-3.6" stroke="black" strokeWidth={1.5} fill="none" />
          </mask>
          <rect {...BOX} fill="currentColor" mask="url(#glyph-survived)" />
        </>
      )}

      {name === 'pushed-back' && (
        <>
          {/* Half-filled, and the fill is the LEFT half: the mark reads as "got part of the way",
              which is what a caveated pass is. The clip is a plain rect rather than a half-width
              path so the filled edge lands exactly on the square's centre line. */}
          <clipPath id="glyph-pushed-left">
            <rect x="0" y="0" width="7" height="14" />
          </clipPath>
          <rect {...BOX} fill="currentColor" clipPath="url(#glyph-pushed-left)" stroke="none" />
          <rect {...BOX} />
        </>
      )}

      {name === 'killed' && (
        <>
          <rect {...BOX} />
          {/* Inset to 4.3/9.7 so the cross clears the corner radius; a full-diagonal X reads as a
              square with its corners cut off at this size. */}
          <path d="M4.6 4.6 9.4 9.4M9.4 4.6 4.6 9.4" />
        </>
      )}

      {name === 'pending' && <rect {...BOX} />}

      {name === 'source' && (
        /* The anchor mark: a paragraph-style stem with a bowl, the printer's convention for "there
           is a reference here". Deliberately NOT a link/chain icon -- a chain says "this goes
           somewhere", and the claim being made is stronger than that: "this carries a receipt". */
        <>
          <path d="M8.6 2.5v9" />
          <path d="M6.2 2.5h4.3" />
          <path d="M6.2 2.5a2.1 2.1 0 0 0 0 4.2h1.2" />
        </>
      )}
    </svg>
  );
}

/**
 * The sixth mark: the killed square plus its two-letter cause code (§3.3).
 *
 * The code is a real text node in the mono face, not a path, so the kill-log taxonomy is
 * selectable, searchable and readable by a screen reader -- the code IS the information here,
 * unlike the five marks above, which restate a word already on the row.
 */
export function KillCauseGlyph({
  cause,
  className,
  label,
}: {
  cause: KillCause;
  className?: string;
  label?: string;
}) {
  return (
    <span className={cx('inline-flex items-center gap-1', className)}>
      <Glyph name="killed" label={label} />
      <span className="font-mono text-caption tabular-nums">{KILL_CAUSE_CODES[cause]}</span>
    </span>
  );
}
