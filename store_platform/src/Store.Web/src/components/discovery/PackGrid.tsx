import Link from 'next/link';
import React from 'react';

import { formatPrice, type Pack } from '@/lib/api/client';
import { splitTitle } from '@/lib/discovery';

import { FacetChips } from './FacetChips';

/**
 * A plain, linkable grid of packs, used by the `/ideas/*` landing pages.
 *
 * WHY NOT REUSE THE HOME PAGE'S CARD. `PackCard` in `pages/index.tsx` is deliberately not
 * exported: it is coupled to the catalogue's filter state and its spotlight/variant logic. Lifting
 * it out would mean editing the busiest page on the site to serve a new one, for a card that needs
 * none of that behaviour. This follows the shape `SimilarPacks` already established instead — the
 * same visual language, no shared state.
 *
 * The whole card is one `<a>`, which is the point: a crawler on a landing page needs a real anchor
 * with the pack's own words in it to follow, and that is exactly what these pages exist to provide.
 */
export function PackGrid({ packs }: { packs: Pack[] }) {
  return (
    <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {packs.map((pack) => {
        const { name, descriptor } = splitTitle(pack.title, pack.headline);
        return (
          <li key={pack.id}>
            <Link
              href={`/pack/${pack.id}`}
              className="flex h-full flex-col rounded-xl border border-border bg-surface p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-text/20 hover:shadow-[0_12px_28px_rgba(0,0,0,0.08)]"
            >
              <h3 className="text-base font-bold leading-snug text-text">{name}</h3>
              {descriptor && <p className="mt-1.5 line-clamp-3 text-sm text-muted">{descriptor}</p>}
              <FacetChips pack={pack} compact max={3} className="mt-4" />
              <span className="mt-4 text-sm font-black text-text">{formatPrice(pack.price)}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
