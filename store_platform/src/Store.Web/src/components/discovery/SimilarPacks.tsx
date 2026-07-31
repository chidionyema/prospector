import Link from 'next/link';
import React from 'react';

import { formatPrice, type Pack } from '@/lib/api/client';
import { similarPacks, splitTitle } from '@/lib/discovery';

import { FacetChips } from './FacetChips';

/**
 * "More like this" keyed on **mechanism**, not sector (spec Part 9).
 *
 * The buyer the row exists for is the one who liked the mechanics of B2B fee recovery and does
 * not want another vets business — so same-sector is a *penalty* in `scoreSimilar`, not a match.
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
      <h2 className="text-xl font-black tracking-tight text-text">Same mechanics, different world</h2>
      <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">
        Like how this one makes money but not the industry it sits in? These work the same way somewhere
        else.
      </p>
      <ul className="mt-5 grid gap-3 sm:grid-cols-3">
        {similar.map((candidate) => {
          const { name, descriptor } = splitTitle(candidate.title, candidate.headline);
          return (
            <li key={candidate.id}>
              <Link
                href={`/pack/${candidate.id}`}
                className="flex h-full flex-col rounded-xl border border-border bg-surface p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-text/20 hover:shadow-[0_12px_28px_rgba(0,0,0,0.08)]"
              >
                <span className="text-sm font-bold leading-snug text-text">{name}</span>
                {descriptor && <span className="mt-1 line-clamp-2 text-xs text-muted">{descriptor}</span>}
                <FacetChips pack={candidate} compact max={3} className="mt-3" />
                <span className="mt-3 text-sm font-black text-text">{formatPrice(candidate.price)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
