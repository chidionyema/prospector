import { cx } from './cx';

/**
 * The one treatment for a link set INSIDE a sentence.
 *
 * Not a component, because an inline link is a `next/link` on an internal route and a bare `<a>`
 * on a mailto or an outbound URL, and wrapping both costs more than it saves. It is the class
 * string, so the rule lives in one place and a call site cannot half-remember it.
 *
 * Measured 2026-08-06 with `getComputedStyle` against the production build on :3111, the buy box
 * on /pack/[id] rendered two inline links, in adjacent paragraphs of the same card, in two
 * different colours:
 *
 *   "creating an account"  color rgb(113, 113, 122)  decoration underline
 *   "refund policy"        color rgb(37, 99, 235)    decoration underline
 *
 * The grey one is the worse of the two: `className="underline"` with no colour inherits
 * `text-muted` from the paragraph, so on the page where a stranger decides whether to spend £79
 * the link explaining what happens to their purchase was the same ink as the sentence around it.
 *
 * Four treatments were in the tree at that point, all of them "the house style" somewhere:
 *
 *   text-accent underline underline-offset-2 hover:text-accent-hover   7 sites  <- the majority
 *   text-primary hover:underline                                      20 sites
 *   font-semibold text-text underline underline-offset-2               7 sites
 *   underline (colour inherited)                                       4 sites
 *
 * The accent form wins on a falsifiable point rather than a headcount: it is the only one of the
 * four that is distinguishable from body prose WITHOUT a pointer. `hover:underline` puts the
 * entire affordance behind a hover, which a touch device never delivers, and the bare `underline`
 * form carries no colour at all.
 *
 * `underline-offset-2` rather than the default: the descenders in "y" and "p" collide with a
 * baseline underline at this text size.
 *
 * ── §3.1 (2026-08-08): THE UNDERLINE IS NOW THE WHOLE AFFORDANCE ───────────────────────────────
 * `--accent` was #2563EB when the analysis above was written, and the argument for this form was
 * that it is "the only one of the four distinguishable from body prose WITHOUT a pointer". Under
 * spec §3.1 colour means "a verdict" and nothing else, so --accent now resolves to ink -- which
 * means an inline link is the same ink as the sentence around it, and that argument now rests
 * ENTIRELY on the underline. That is why the decoration is specified here rather than left to
 * the default: at `decoration-border-strong` the rule is a hairline that reads as a link without
 * competing with the text, and hover promotes it to full ink rather than changing hue. Remove the
 * underline and a link becomes genuinely unfindable -- it is no longer a style choice.
 */
export const textLinkClass = (className?: string) =>
  cx(
    // `underline-offset-4`, raised from 2 on 2026-08-14 (founder, from a screenshot of "Why prices
    // differ"): 2px was still inside the descender depth of this face at `text-meta`, so the rule
    // cut through the y and the p exactly as the un-offset default did -- the fix documented above
    // was directionally right and short by 2px. It is set in px-equivalents rather than as an em
    // ratio because Tailwind's offsets are absolute and the sizes this class serves are within one
    // step of each other.
    // `tlink` is the drawing's own inline-link class (`mockup.css:44`), and every one of the
    // twelve mockups uses it: `color:var(--link);font-weight:550`. The weight is what was missing
    // here -- `--accent` already resolves to `--link` (brandV3.test.ts) so the colour matched, but
    // a link at body weight sits flatter in a paragraph than the drawing draws it. The underline
    // utilities stay on top of it deliberately: `.tlink` underlines on hover only, and this site
    // keeps a permanent hairline underline because the accent alone is not a findable affordance.
    'tlink',
    'text-accent underline decoration-border-strong underline-offset-4 transition-colors',
    'hover:decoration-text hover:text-accent-hover',
    className,
  );
