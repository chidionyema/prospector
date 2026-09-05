import React from 'react';

import { type Pack } from '@/lib/api/client';

import { PackRowList } from './PackRow';

/**
 * "More like this" keyed on **mechanism**, not sector (spec Part 9).
 *
 * The buyer the row exists for is the one who liked the mechanics of B2B fee recovery and does
 * not want another vets business, so same-sector is a *penalty* in `scoreSimilar`, not a match.
 *
 * `items` arrives pre-scored: the caller (`pages/pack/[id].tsx`) runs `similarPacks` server-side
 * against the full catalogue and hands this component only the (at most 3) matches, not the
 * catalogue -- see that page's `similar` prop for why. The row still hides itself entirely on an
 * empty list (AC-21): `similarPacks` already returns `[]` unless at least two candidates score
 * above 0, so "no items" here means the same thing it always did.
 */
export function SimilarPacks({ items }: { items: Pack[] }) {
  if (items.length === 0) return null;

  return (
    <section className="mt-12">
      <h2 className="sec">Related packs</h2>
      <p className="mt-2 lede">
        Like how this one makes money but not the industry it sits in? These work the same way somewhere
        else.
      </p>
      {/* Rows, was a three-up `DossierCard` grid. Same reason as everywhere else on the site
          (2026-08-15 brief): two card formats never share a page, and this row sat under a pack
          page that is itself one long single-pack presentation. */}
      <PackRowList className="mt-5" packs={items} />
    </section>
  );
}
