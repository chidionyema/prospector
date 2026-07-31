import React, { useState } from 'react';

import { Button, Checkbox, Input } from '@/components/ui';
import { joinWaitlist } from '@/lib/api/client';
import type { DiscoveryState } from '@/lib/discovery';
import { KIND_LABEL, label, type FacetKind } from '@/lib/facets';

/**
 * Near miss before empty, and only then the waitlist (spec Part 7).
 *
 * The order is the point. A filtered empty state is common — most of the time the buyer had a
 * purchasable pack one facet away — and sending them straight to an email form burns a sale that
 * was on the table. So: relax a constraint first, capture an address only when the catalogue
 * genuinely has nothing. That order holds as the catalogue grows; it is not tuned to a size.
 *
 * Named `Discovery*` on purpose — `components/ui` already exports an unrelated `EmptyState`.
 */

/** The consent sentence the buyer is shown. The API hashes exactly this text as the evidence of
 *  what was consented to, so it must not drift from what is rendered. */
export const WAITLIST_CONSENT_TEXT =
  'One email, only if a pack ships. No newsletter. Unsubscribe in one click.';

/** Must match `WaitlistService.CurrentConsentVersion` in the API. */
export const WAITLIST_CONSENT_VERSION = 'waitlist-2026-07-30';

export interface NearMissCandidate {
  pack: { id: string; title: string };
  /** Which active constraint this pack fails, in buyer-facing words. */
  missLabel: string;
  /** The state that would include it — the one-tap relaxer. */
  relaxedState: DiscoveryState;
  relaxLabel: string;
}

/**
 * A. Near miss — packs matching all but one active constraint, each with a chip naming the miss
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
        Nothing matches all of it. These come closest —
      </h3>
      <ul className="mt-3 flex flex-wrap gap-2">
        {candidates.map((candidate) => (
          <li
            key={candidate.pack.id}
            className="rounded-full bg-warning/10 px-3 py-1 text-[11px] font-semibold text-text/80 ring-1 ring-inset ring-warning/30"
          >
            {candidate.pack.title.split(/[—–]/)[0].trim()}: {candidate.missLabel}
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

type SubmitState = 'idle' | 'sending' | 'queued' | 'error';

/**
 * B. True empty, catalogue-wide — the waitlist.
 *
 * The consent box is **unticked by default** and the submit is refused without it, client-side
 * here and server-side in `WaitlistService`. A pre-ticked box is not consent under UK GDPR, and
 * the italic sentence under the form is the exact text the server hashes as evidence.
 */
export function DiscoveryWaitlist({ query }: { query: string }) {
  const [email, setEmail] = useState('');
  const [consent, setConsent] = useState(false);
  const [state, setState] = useState<SubmitState>('idle');
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!consent) {
      setError('Tick the box and we can email you. Without it we have no lawful basis to.');
      return;
    }
    setState('sending');
    setError(null);
    try {
      const result = await joinWaitlist({
        email,
        consent,
        consentText: WAITLIST_CONSENT_TEXT,
        consentVersion: WAITLIST_CONSENT_VERSION,
        query,
        source: 'catalogue-empty-state',
      });
      if (!result.ok) {
        setError(result.error);
        setState('error');
        return;
      }
      setState('queued');
    } catch {
      setError('That did not go through. Try again in a moment.');
      setState('error');
    }
  };

  if (state === 'queued') {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6">
        <h3 className="text-lg font-black tracking-tight text-text">You&apos;re in the queue.</h3>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          We&apos;ll email you from support@mumchimp.com if a pack in this space survives the six checks.
          Nothing else.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border bg-surface p-6">
      <h3 className="text-lg font-black tracking-tight text-text">
        No vetted pack for “{query.trim()}” — yet.
      </h3>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
        We only list an idea once it survives six checks with a clickable source behind every claim. Most
        ideas in a hot space die on the incumbent test. Tell us where to point the engine and we&apos;ll
        email you if one survives.
      </p>

      <form onSubmit={submit} className="mt-5 flex max-w-md flex-col gap-3">
        <Input
          label="Email"
          type="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
          error={error ?? undefined}
        />
        <Checkbox
          label="Email me if a pack in this space survives"
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
        />
        <Button type="submit" variant="prominent" disabled={state === 'sending'}>
          {state === 'sending' ? 'Adding you…' : 'Put it in the queue'}
        </Button>
      </form>

      <p className="mt-3 text-xs italic text-muted">{WAITLIST_CONSENT_TEXT}</p>
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
  if (!actualText) return `Not tagged for ${KIND_LABEL[kind].toLowerCase()}, you said ${wantedText.toLowerCase()}`;
  return `${actualText}, you said ${wantedText.toLowerCase()}`;
}
