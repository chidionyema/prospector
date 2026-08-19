import React from 'react';

import { type Pack } from '@/lib/api/client';

import { PackRowList } from './PackRow';

/**
 * The pack list on the `/ideas/*` landing pages.
 *
 * ONE FORMAT SITEWIDE (2026-08-15, founder's mobile brief). This was a `minmax(300px, 1fr)` grid
 * of `DossierCard`s, a card format that existed only here and on the pack page. Its own docblock
 * argued for the split -- "`PackCard` in `pages/index.tsx` is deliberately not exported: it is
 * coupled to the catalogue's filter state" -- and that was true of the card as it stood. The fix
 * was to decouple the row, not to keep a second card: `PackRow` takes a pack, a currency and two
 * optional display flags, and knows nothing about filter state. So the argument for a separate
 * component no longer holds, and the cost it was paying for did: a landing page and the shelf
 * showed the same pack in two different shapes.
 *
 * The whole row is one `<a>`, which is the point: a crawler on a landing page needs a real anchor
 * with the pack's own words in it to follow, and that is exactly what these pages exist to provide.
 *
 * `omitFacet` is GONE with the card. It suppressed the facet chips a `DossierCard` printed; rows
 * carry no chips, so there is nothing left to suppress.
 */
export function PackGrid({ packs }: { packs: Pack[] }) {
  return <PackRowList packs={packs} />;
}
