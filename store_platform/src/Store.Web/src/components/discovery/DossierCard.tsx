import Link from 'next/link';
import React from 'react';

import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { freshnessLabel, type Pack } from '@/lib/api/client';
import { useCurrency } from '@/lib/currency';
import { formatPriceForMarket } from '@/lib/fx';
import { cardHeading } from '@/lib/discovery';

import { FacetChips } from './FacetChips';

/**
 * DossierCard, a mini-card matching PackCard's design language.
 *
 * Same border, hover treatment and evidence line as the full `PackCard` in `pages/index.tsx`,
 * but smaller padding, no buy button, and no FitChips cap of 5. Used by SimilarPacks and PackGrid
 * so those surfaces don't carry their own hardcoded card markup, which has already drifted from
 * the catalogue card once.
 *
 * Brand v3 (2026-08-06): `ring-1 ring-black/[0.06]` became a real `border-border` hairline (a
 * ring is drawn outside the box, so a ringed card and a bordered card in the same grid sit on
 * different pixel columns), the tinted `hover:bg-primary/[0.02]` wash and the
 * `group-hover:text-primary` title recolour went (the whole card is the link, not the title), and
 * the evidence line moved to mono because every token in it is a checkable quantity.
 *
 * That line no longer prints `6/6 checks`. The count is lane-dependent and `GET /catalog` carries
 * no check field, so the token was a constant standing in for a number the card had never been
 * told -- false for 21 of the 61 packs listed on 2026-08-06. See `parseCheckCounts` in
 * lib/api/client.ts; the real count is stated on the pack page, where the API supplies it.
 */
export function DossierCard({ pack }: { pack: Pack }) {
  // Ambient, not a prop: SimilarPacks and PackGrid are layout, they have no business knowing
  // about money, and a card quoting GBP beside a converted headline is the exact defect
  // measured on the pack page's related rail. See lib/currency.tsx.
  const currency = useCurrency();
  // `cardHeading`, the same helper the homepage grid uses, NOT `splitTitle`. This card used to
  // head every pack with its brand name while the homepage headed the same pack with its short
  // descriptive line, so the two shelves named one product two ways.
  const { heading, sub } = cardHeading(pack);
  const line = pack.oneLine || sub;
  const sources =
    typeof pack.sourceCount === 'number' && pack.sourceCount > 0 ? pack.sourceCount : null;
  const fresh = freshnessLabel(pack.verifiedAt);

  return (
    <Link
      href={`/pack/${pack.id}`}
      className={cx(
        'group flex h-full flex-col rounded-md border border-border bg-surface p-5',
        'transition-[border-color,box-shadow,transform] duration-[180ms] ease-[cubic-bezier(0.2,0,0,1)]',
        'hover:-translate-y-px hover:border-border-strong hover:shadow-1',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
      )}
    >
      <span className="line-clamp-2 text-meta font-semibold leading-snug text-text">{heading}</span>
      {line && <span className="mt-1 line-clamp-2 text-caption text-muted">{line}</span>}

      <FacetChips pack={pack} compact className="mt-3" />

      {(sources !== null || fresh) && (
        <p className="mt-3 flex flex-wrap items-center gap-x-1.5 font-mono text-caption text-subtle">
          <Icon name="verified" size={12} className="text-success" />
          {sources !== null && (
            <>
              <span>{sources} sources</span>
              {fresh && <span aria-hidden="true">·</span>}
            </>
          )}
          {fresh && <span>{fresh}</span>}
        </p>
      )}

      <span className="mt-auto pt-4 font-mono text-meta font-semibold text-text">
        {formatPriceForMarket(pack.price, currency)}
      </span>
    </Link>
  );
}
