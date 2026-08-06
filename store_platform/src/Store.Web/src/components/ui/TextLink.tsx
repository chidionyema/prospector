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
 */
export const textLinkClass = (className?: string) =>
  cx(
    'text-accent underline underline-offset-2 transition-colors hover:text-accent-hover',
    className,
  );
