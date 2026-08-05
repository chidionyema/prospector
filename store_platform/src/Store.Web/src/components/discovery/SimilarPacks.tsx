import React from 'react';

import { type Pack } from '@/lib/api/client';
import { similarPacks } from '@/lib/discovery';

import { DossierCard } from './DossierCard';

/**
 * "More like this" keyed on **mechanism**, not sector (spec Part 9).
 *
 * The buyer the row exists for is the one who liked the mechanics of B2B fee recovery and does
 * not want another vets business, so same-sector is a *penalty* in `scoreSimilar`, not a match.
 *
 * The row hides itself entirely when fewer than two candidates score above 0 (AC-21). On a
 * mostly-untagged catalogue that is the common case, and one weak suggestion under "more like
 * this" is a worse signal than no row at all.
 */
export function SimilarPacks({ pack, all }: { pack: Pack; all: Pack[] }) {
  const similar = similarPacks(pack, all);
  if (similar.length === 0) return null;

  return (
    <section className="mt-12">
      <h2 className="text-h2 font-black tracking-tight text-text">Same mechanics, different world</h2>
      <p className="mt-1 max-w-2xl text-meta leading-relaxed text-muted">
        Like how this one makes money but not the industry it sits in? These work the same way somewhere
        else.
      </p>
      <ul className="mt-5 grid gap-3 sm:grid-cols-3">
        {similar.map((candidate) => (
          <li key={candidate.id}>
            <DossierCard pack={candidate} />
          </li>
        ))}
      </ul>
    </section>
  );
}
