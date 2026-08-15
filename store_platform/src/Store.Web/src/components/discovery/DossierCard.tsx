import Link from 'next/link';
import React from 'react';

import { EvidenceBar } from '@/components/ui/EvidenceBar';
import { PackCardHeader } from '@/components/ui/PackCardHeader';
import { cx } from '@/components/ui/cx';
import { freshnessLabel, type Pack } from '@/lib/api/client';
import { categoryFor } from '@/lib/category';
import { useCurrency } from '@/lib/currency';
import type { FacetKind } from '@/lib/facets';
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
 * ONE HEADER, ONE HEADING (2026-08-15). Both now come from the same place as the shelf card's:
 * `PackCardHeader` for the band, `h3 text-body font-semibold leading-snug` for the title. This
 * card is smaller than the shelf card and stays smaller -- a two-line clamp, no buy button --
 * but it is no longer a DIFFERENT card. What it was: an 80px near-black plate and a `span` one
 * type step down, i.e. the one surface that never got the founder's 2026-08-14 ruling.
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
export function DossierCard({
  pack,
  omitFacet,
}: {
  pack: Pack;
  /** The facet the surrounding page already states. See `FacetChips`'s `omit`. */
  omitFacet?: { kind: FacetKind; value: string } | null;
}) {
  // Ambient, not a prop: SimilarPacks and PackGrid are layout, they have no business knowing
  // about money, and a card quoting GBP beside a converted headline is the exact defect
  // measured on the pack page's related rail. See lib/currency.tsx.
  const currency = useCurrency();
  // `cardHeading`, the same helper the homepage grid uses, NOT `splitTitle`. This card used to
  // head every pack with its brand name while the homepage headed the same pack with its short
  // descriptive line, so the two shelves named one product two ways.
  const { heading, sub } = cardHeading(pack);
  const line = pack.oneLine || sub;
  const cat = categoryFor(pack);
  const fresh = freshnessLabel(pack.verifiedAt);

  return (
    <Link
      href={`/pack/${pack.id}`}
      className={cx(
        'group flex h-full flex-col overflow-hidden rounded-md border border-border bg-surface',
        'transition-[border-color,box-shadow,transform] duration-[180ms] ease-[cubic-bezier(0.2,0,0,1)]',
        'hover:-translate-y-px hover:border-border-strong',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
      )}
    >
      {/* THE SHARED HEADER (2026-08-15). This was an 80px `bg-ins-bg` plate -- a scaled copy of
          `PackCoverArt`, which was DELETED from the homepage on 2026-08-14 when the founder ruled
          the black media block out. The ruling landed on index.tsx and never reached here, so for
          a day the same pack wore a near-black plate on /ideas/<slug> (the shelf search engines
          land people on) and a pale band on the home shelf. The comment that used to sit here
          still claimed this was "the SAME drawing as `PackCoverArt` in pages/index.tsx", by then a
          component that did not exist.

          It is now literally the same element as every other pack card's, because it is the same
          component. See `PackCardHeader`. */}
      <PackCardHeader label={cat.tagged ? cat.label : null} labelClassName={cat.ink} />

      <div className="flex flex-1 flex-col p-6">
        {/* `h3` at `text-body`, matching the shelf card (index.tsx). It was a `span` at
            `text-meta`: one size smaller AND not a heading element at all, so a screen reader
            walking /ideas/<slug> by heading found the page title and then nothing for twenty
            products. The content helper was unified months ago (`cardHeading`); the styling and
            the semantics were not. */}
        <h3 className="line-clamp-2 text-body font-semibold leading-snug text-text">{heading}</h3>
        {line && <p className="mt-1 line-clamp-2 text-caption text-muted">{line}</p>}

        <FacetChips pack={pack} compact omit={omitFacet} className="mt-3" />

        {/* THE EVIDENCE RUN, IN THE BODY, IN THE CARD'S ORDINARY INK. It used to be the lit thing
            on the dark plate; the plate is what went, not the fact. `tone` drops to the default,
            which is the whole point of the tone prop -- the same run, drawn for a light surface
            (`--survive` ticks, `--subtle` label) instead of an instrument one. */}
        <div className="mt-3">
          <EvidenceBar count={pack.sourceCount} />
        </div>

        {fresh && <p className="mt-3 font-mono text-caption text-subtle">{fresh}</p>}

        <span className="mt-auto pt-4 font-mono text-meta font-semibold text-text">
          {formatPriceForMarket(pack.price, currency)}
        </span>
      </div>
    </Link>
  );
}
