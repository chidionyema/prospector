import React from 'react';

import { Button } from '@/components/ui';
import { WaitlistForm } from '@/components/waitlist/WaitlistForm';
import type { DiscoveryState } from '@/lib/discovery';
import { KIND_NOUN, label, type FacetKind } from '@/lib/facets';

/**
 * Near miss before empty, and only then the waitlist (spec Part 7).
 *
 * The order is the point. A filtered empty state is common, most of the time the buyer had a
 * purchasable pack one facet away, and sending them straight to an email form burns a sale that
 * was on the table. So: relax a constraint first, capture an address only when the catalogue
 * genuinely has nothing. That order holds as the catalogue grows; it is not tuned to a size.
 *
 * Named `Discovery*` on purpose, `components/ui` already exports an unrelated `EmptyState`.
 */

export interface NearMissCandidate {
  pack: { id: string; title: string };
  /** Which active constraint this pack fails, in buyer-facing words. */
  missLabel: string;
  /** The state that would include it, the one-tap relaxer. */
  relaxedState: DiscoveryState;
  relaxLabel: string;
}

/**
 * A. Near miss, packs matching all but one active constraint, each with a chip naming the miss
 * and a one-tap relaxer. No email form here: there is still something to sell.
 */
export function DiscoveryNearMiss({
  candidates,
  onRelax,
  children,
}: {
  candidates: NearMissCandidate[];
  onRelax: (state: DiscoveryState) => void;
  /** The cards themselves, rendered by the page so this component owns no card layout. */
  children?: React.ReactNode;
}) {
  const relaxers = candidates.filter(
    (candidate, index, all) => all.findIndex((c) => c.relaxLabel === candidate.relaxLabel) === index,
  );

  return (
    <div className="rounded-2xl border border-border bg-surface p-6">
      <h3 className="text-lg font-black tracking-tight text-text">
        Nothing matches all of it. These come closest,
      </h3>
      <ul className="mt-3 flex flex-wrap gap-2">
        {candidates.map((candidate) => (
          <li key={candidate.pack.id}>
            <button
              type="button"
              onClick={() => onRelax(candidate.relaxedState)}
              className="rounded-full bg-warning/10 px-3 py-1 text-[11px] font-semibold text-text/80 ring-1 ring-inset ring-warning/30 transition-colors hover:bg-warning/20"
            >
              {candidate.pack.title.split(/\s*,\s*/)[0].trim()}: {candidate.missLabel}
            </button>
          </li>
        ))}
      </ul>
      {children}
      {relaxers.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {relaxers.map((candidate) => (
            <Button
              key={candidate.relaxLabel}
              variant="secondary"
              onClick={() => onRelax(candidate.relaxedState)}
            >
              {candidate.relaxLabel}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * B. True empty, catalogue-wide, the waitlist.
 *
 * The form itself (and the consent wording the server hashes) now lives in
 * `components/waitlist/WaitlistForm`, shared with the standing callout on the sample report. This
 * component keeps only what is specific to arriving here: the copy naming the failed search, and
 * the `catalogue-empty-state` source tag that keeps the two placements tellable apart.
 */
export function DiscoveryWaitlist({ query, onReset }: { query: string; onReset?: () => void }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6">
      <h3 className="text-lg font-black tracking-tight text-text">
        No vetted pack for “{query.trim()}”, yet.
      </h3>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
        We only list an idea once it survives six checks with a clickable source behind every claim. Most
        ideas in a hot space die on the incumbent test. Tell us where to point the engine and we&apos;ll
        email you if one survives.
      </p>

      {onReset && (
        <div className="mt-5">
          <Button variant="secondary" onClick={onReset}>
            Reset all filters
          </Button>
        </div>
      )}

      <div className="mt-5">
        <WaitlistForm source="catalogue-empty-state" query={query} />
      </div>

      <p className="mt-2 text-xs font-medium text-text/70">
        Meanwhile, the free sample report shows exactly what survives looks like →
      </p>
    </div>
  );
}

/** Human-readable name of the constraint a near-miss pack fails, for the chip copy. */
export function missLabelFor(kind: FacetKind, wanted: string, actual: string | null | undefined): string {
  const wantedText = label(kind, wanted) ?? wanted;
  const actualText = label(kind, actual);
  if (!actualText) return `Not tagged for ${KIND_NOUN[kind]}, you said ${wantedText.toLowerCase()}`;
  return `${actualText}, you said ${wantedText.toLowerCase()}`;
}
