import React from 'react';

import { type Pack } from '@/lib/api/client';
import type { FacetKind } from '@/lib/facets';

import { DossierCard } from './DossierCard';

/**
 * A plain, linkable grid of packs, used by the `/ideas/*` landing pages.
 *
 * WHY NOT REUSE THE HOME PAGE'S CARD. `PackCard` in `pages/index.tsx` is deliberately not
 * exported: it is coupled to the catalogue's filter state and its spotlight/variant logic. Lifting
 * it out would mean editing the busiest page on the site to serve a new one, for a card that needs
 * none of that behaviour. This follows the shape `SimilarPacks` already established instead, the
 * same visual language, no shared state.
 *
 * The whole card is one `<a>`, which is the point: a crawler on a landing page needs a real anchor
 * with the pack's own words in it to follow, and that is exactly what these pages exist to provide.
 */
export function PackGrid({
  packs,
  omitFacet,
}: {
  packs: Pack[];
  /**
   * The facet this shelf is SELECTED BY, so no card repeats it. A landing page passes the
   * `{kind, value}` it filters on; see `FacetChips`'s `omit` for the measurement.
   */
  omitFacet?: { kind: FacetKind; value: string } | null;
}) {
  return (
    // §3.4: `minmax(300px, 1fr)`, not a breakpoint ladder. The ladder pinned the card count to the
    // VIEWPORT (1 / 2 / 3 at sm and lg) rather than to the space a card actually needs, so at
    // 1024px three cards were squeezed to 320px each while at 1023px two sat at 480px -- the same
    // card, two sizes, decided by a number unrelated to its content. auto-fill lets the row take
    // as many 300px-or-wider columns as fit, which is the same rule at every width.
    // No top margin. The grid is the first thing inside its `Section`, so `mt-10` was 40px added
    // to the band's own opening padding -- measured 2026-08-14, it put 129px between the rule
    // under the hero and the first card on /ideas/<slug>. A layout component owns the space
    // BETWEEN its items; the space above it belongs to whatever it sits in.
    <ul className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(300px,1fr))]">
      {packs.map((pack) => (
        <li key={pack.id}>
          <DossierCard pack={pack} omitFacet={omitFacet} />
        </li>
      ))}
    </ul>
  );
}
