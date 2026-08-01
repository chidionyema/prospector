import Link from 'next/link';
import React from 'react';

import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { formatPrice, freshnessLabel, type Pack } from '@/lib/api/client';
import { splitTitle } from '@/lib/discovery';

import { FacetChips } from './FacetChips';

/**
 * DossierCard, a mini-card matching PackCard's design language.
 *
 * Same radius, hover treatment and proof line as the full PackCard, but smaller padding (p-5),
 * no BuyNow/AddToCart buttons, and no FitChips cap of 5. Used by SimilarPacks and PackGrid so
 * those surfaces don't carry their own hardcoded card markup, which has already drifted from the
 * catalogue card once.
 */
export function DossierCard({ pack }: { pack: Pack }) {
  const { name, descriptor } = splitTitle(pack.title, pack.headline);
  const sources =
    typeof pack.sourceCount === 'number' && pack.sourceCount > 0 ? pack.sourceCount : null;
  const fresh = freshnessLabel(pack.verifiedAt);

  return (
    <Link
      href={`/pack/${pack.id}`}
      className={cx(
        'group flex h-full flex-col rounded-lg bg-white p-5 ring-1 ring-black/[0.06] transition-[background-color,box-shadow] duration-200',
        'hover:bg-primary/[0.02] hover:shadow-[0_10px_15px_-3px_rgba(15,23,42,0.08)] hover:ring-black/[0.18]',
      )}
    >
      <span className="text-sm font-bold leading-snug text-text transition-colors group-hover:text-primary">
        {name}
      </span>
      {descriptor && <span className="mt-1 line-clamp-2 text-xs text-muted">{descriptor}</span>}

      <FacetChips pack={pack} compact className="mt-3" />

      {(sources !== null || fresh) && (
        <p className="mt-2.5 flex flex-wrap items-center gap-x-1.5 text-[11px] font-medium text-muted">
          <Icon name="verified" size={12} className="text-primary" />
          <span className="font-bold text-text/80">6 / 6</span>
          {sources !== null && (
            <>
              <span aria-hidden="true">·</span>
              <span>
                <span className="font-bold text-text/80">{sources}</span> sources
              </span>
            </>
          )}
          {sources !== null && fresh && <span aria-hidden="true">·</span>}
          {fresh && <span>{fresh}</span>}
        </p>
      )}

      <span className="mt-auto pt-4 text-sm font-black text-text">{formatPrice(pack.price)}</span>
    </Link>
  );
}
