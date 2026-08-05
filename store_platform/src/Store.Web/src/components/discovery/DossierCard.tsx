import Link from 'next/link';
import React from 'react';

import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { freshnessLabel, type Pack } from '@/lib/api/client';
import { useCurrency } from '@/lib/currency';
import { formatPriceForMarket } from '@/lib/fx';
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
  // Ambient, not a prop: SimilarPacks and PackGrid are layout, they have no business knowing
  // about money, and a card quoting GBP beside a converted headline is the exact defect
  // measured on the pack page's related rail. See lib/currency.tsx.
  const currency = useCurrency();
  const { name, descriptor } = splitTitle(pack.title, pack.headline);
  const sources =
    typeof pack.sourceCount === 'number' && pack.sourceCount > 0 ? pack.sourceCount : null;
  const fresh = freshnessLabel(pack.verifiedAt);

  return (
    <Link
      href={`/pack/${pack.id}`}
      className={cx(
        'group flex h-full flex-col rounded-md bg-surface p-5 ring-1 ring-black/[0.06] transition-[background-color,box-shadow] duration-200',
        'hover:bg-primary/[0.02] hover:ring-black/[0.18]',
      )}
    >
      <span className="text-meta font-bold leading-snug text-text transition-colors group-hover:text-primary">
        {name}
      </span>
      {descriptor && <span className="mt-1 line-clamp-2 text-caption text-muted">{descriptor}</span>}

      <FacetChips pack={pack} compact className="mt-3" />

      {(sources !== null || fresh) && (
        <p className="mt-2.5 flex flex-wrap items-center gap-x-1.5 text-caption font-medium text-muted">
          <Icon name="verified" size={12} className="text-success" />
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

      <span className="mt-auto pt-4 text-meta font-black text-text">{formatPriceForMarket(pack.price, currency)}</span>
    </Link>
  );
}
