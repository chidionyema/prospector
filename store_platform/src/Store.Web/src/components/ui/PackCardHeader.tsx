import React from 'react';

import { cx } from './cx';

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
        'flex h-10 w-full flex-none items-center gap-x-2 overflow-hidden px-6',
        'border-b border-border bg-surface2',
        className,
      )}
    >
      {label && (
        <span className={cx('truncate font-mono text-caption', labelClassName ?? 'text-subtle')}>
          {label}
        </span>
      )}
    </span>
  );
}

export default PackCardHeader;
