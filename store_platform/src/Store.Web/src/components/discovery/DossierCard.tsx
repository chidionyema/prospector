import Link from 'next/link';
import React from 'react';

import { EvidenceBar } from '@/components/ui/EvidenceBar';
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
      {/* THE COVER, at the small size (2026-08-14).
          A pack was a different object depending on which shelf you found it on: the home page
          drew it on the instrument plate with its evidence run as the artwork, while /ideas/<slug>
          -- the shelf a search engine actually lands people on -- drew a white rectangle with a
          green tick and a number in the body. Same product, two identities, and the weaker one on
          the page with the inbound traffic.

          This is the SAME drawing as `PackCoverArt` in pages/index.tsx, scaled: same ground, same
          bottom-left lift, same sector line in mono, same `EvidenceBar` component with
          `tone="instrument"` at its `sm` step. 80px rather than 112px because this card also
          serves the `SimilarPacks` rail, where it is a secondary object on a page that already has
          a masthead; the cover must not out-weigh what it sits under.

          `size` stays at the default `sm`: the tick shape is the same 5-step skyline either way
          (see EvidenceBar), so a 26-source pack is recognisably the same run here as on the home
          shelf, just smaller. */}
      <div className="relative flex h-20 flex-col justify-between overflow-hidden border-b border-ins-line bg-ins-bg px-5 py-3.5">
        <div
          aria-hidden
          className={cx(
            'pointer-events-none absolute inset-0',
            // Literal, not a token, and identical to the home cover's: it is a surface texture
            // rather than a semantic colour. Tailwind scans source text, so it must stay a full
            // literal class string and can never be built by interpolation.
            'bg-[image:radial-gradient(120%_80%_at_12%_100%,rgb(250_250_250/0.07),transparent_60%)]',
          )}
        />
        <span className="relative min-w-0 truncate font-mono text-caption text-ins-muted">
          {cat.tagged ? cat.label : null}
        </span>
        {/* The evidence line moved OUT of the body and onto the plate, which is where the green
            `Glyph name="source"` went with it. That glyph was the site's "one cited source" mark
            printed once, beside a number, in success green -- a verdict colour on a fact that is
            not a verdict. The run states the same number and can be compared card to card. */}
        <span className="relative">
          <EvidenceBar count={pack.sourceCount} tone="instrument" />
        </span>
      </div>

      <div className="flex flex-1 flex-col p-5">
        <span className="line-clamp-2 text-meta font-semibold leading-snug text-text">{heading}</span>
        {line && <span className="mt-1 line-clamp-2 text-caption text-muted">{line}</span>}

        <FacetChips pack={pack} compact omit={omitFacet} className="mt-3" />

        {fresh && <p className="mt-3 font-mono text-caption text-subtle">{fresh}</p>}

        <span className="mt-auto pt-4 font-mono text-meta font-semibold text-text">
          {formatPriceForMarket(pack.price, currency)}
        </span>
      </div>
    </Link>
  );
}
