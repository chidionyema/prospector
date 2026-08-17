import React from 'react';

import { cx } from './cx';

/**
 * THE CATEGORY LABEL, one string, used by both card formats.
 *
 * NOT MONOSPACE ANY MORE (2026-08-15, brief Part One item 3). The house rule this site actually
 * holds is `tokens.css` §3.2 -- "Commit Mono for anything the engine produced ... monospace is
 * the site's promise that a string is checkable". A sector is a TAXONOMY, not a measurement:
 * nobody checks "Licensing and admin" against a source. Setting it in the same face as the source
 * counts and the prices spent the promise on a label that makes none, which is what put four mono
 * runs on one row and made the meta line read as a single run-on string.
 *
 * Caps at `text-caption` with `0.06em` of tracking is the replacement: it separates the label
 * from the body text by RHYTHM rather than by face, so mono stays meaningful where it is still
 * used (the figure, the price, the market flag, the "seen" marker).
 *
 * THE CAPS ARE NOT IN THIS STRING and must not be. `__tests__/weightAndCasePolicy.test.ts` bans
 * the `uppercase` utility repo-wide: CSS caps leave the accessible name in sentence case while a
 * screen reader may spell out the rendered form, so the house rule is to uppercase the VALUE
 * (`label.toUpperCase()`). This constant carries the tracking and the weight only.
 */
export const CATEGORY_LABEL = 'tracking-[0.06em] font-medium';


/**
 * THE header of a pack card. Every pack card on the site opens with this and only this.
 *
 * WHY IT IS A COMPONENT (2026-08-15). It was four hand-rolled headers in three files, and that
 * is the whole reason the shelf looked like two different shops: on 2026-08-14 the founder ruled
 * the near-black media block out ("Remove the black media block until there is real imagery for
 * it", docs/SITE_SPEC_PROGRAM.md:1007), the ruling was applied at the call site that happened to
 * be open -- the homepage mid card -- and the other three carried on wearing it. `DossierCard`
 * kept a doc comment claiming it drew "the SAME drawing as `PackCoverArt` in pages/index.tsx"
 * for a day after `PackCoverArt` was deleted. A verdict cannot half-land on a component; it
 * could, and did, half-land on four copies.
 *
 * THE BAND. `--surface2` is the token whose own comment names this exact use ("Sunken/tinted
 * panels: plate headers, table heads, footer, code", tokens.css:83): one notch off white, closed
 * by a hairline. It separates the header from the body without competing with anything in it,
 * and -- the point -- it cannot be mistaken for a photo that failed to load, which is what killed
 * the dark plate twice in one day at two different heights.
 *
 * FIXED HEIGHT, ALWAYS RENDERED. An untagged pack (9 of 63 live) gets the band with no label
 * rather than no band. The band is outside the body's flow, so an empty one costs nothing and
 * keeps every title in a grid on the same baseline. That is the jitter rule: the sector renders
 * only when the pack carries one, so as the body's first child it moved every neighbouring
 * title's baseline by ~34px on any row with a mix.
 *
 * `labelClassName` carries the category hue (`cat.ink`). That is the one documented colour
 * exception on the shelf -- the 12 `--cat-*` hues carry discovery meaning -- and it is a prop
 * rather than a lookup here so this component knows nothing about categories.
 */
export function PackCardHeader({
  label,
  labelClassName,
  className,
}: {
  /** The sector, or null on the 9-of-63 packs that carry none. */
  label?: string | null;
  /** The category ink. Omit for the default subtle grey. */
  labelClassName?: string;
  className?: string;
}) {
  return (
    <span
      className={cx(
        // `px-6`, matching the card body beneath it. The two insets are a single edge as far as a
        // reader is concerned -- a header at 20px over a body at 24px is a 4px step the eye reads
        // as a mistake rather than as two elements. The lead card, whose body opens out to `p-8`
        // from `sm`, passes `sm:px-8` through `className` so it keeps that edge too.
        /* NO STRIP (2026-08-15, brief Part One item 3: "no background strip"). The band was
           `bg-surface2` closed by a hairline, and the docblock above still carries the argument
           for it -- it was the answer to a near-black media plate that read as a failed image
           load. That is a real argument against the PLATE and it does not extend to a tinted bar:
           on a card that now has no artwork at all, a filled strip above the title is a second
           object competing with the one thing the card is for. The label stays where it was and
           the fill goes.

           THE HEIGHT STAYS, and it is the whole reason this is still a band rather than a line of
           text in the body: 9 of 63 live packs carry no sector, and an empty box that reserves
           the space keeps every title in a run on the same baseline. That is the jitter rule
           below, unchanged -- it was never about the fill. */
        'flex h-10 w-full flex-none items-center gap-x-2 overflow-hidden px-6',
        className,
      )}
    >
      {label && (
        <span className={cx('truncate text-caption', CATEGORY_LABEL, labelClassName ?? 'text-subtle')}>
          {label.toUpperCase()}
        </span>
      )}
    </span>
  );
}

export default PackCardHeader;
