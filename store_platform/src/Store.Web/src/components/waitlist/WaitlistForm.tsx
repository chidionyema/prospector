import React, { useState } from 'react';

import { Button, Checkbox, Input } from '@/components/ui';
import { joinWaitlist } from '@/lib/api/client';

/**
 * The one waitlist form, shared by every placement.
 *
 * It lives here rather than inside `discovery/EmptyState` because there is now more than one
 * honest moment to ask for an address, and the consent wording is the thing that must NOT be
 * copy-pasted between them. `WaitlistService` hashes `consentText` as the evidence of what the
 * person agreed to; two placements with two hand-written sentences would produce two hashes for
 * one promise, and the stored evidence would stop meaning anything. One constant, one form.
 *
 * What a placement may vary: the surrounding copy and the `source` tag. What it may not: the
 * promise. Every caller sends the same `WAITLIST_CONSENT_TEXT`, so the promise below is the
 * promise everywhere.
 */

/** The consent sentence the buyer is shown. The API hashes exactly this text as the evidence of
 *  what was consented to, so it must not drift from what is rendered.
 *
 *  Note what it says: "No newsletter". This is a notify-me-on-publish list, not a marketing list.
 *  A placement that implies a regular send is making a promise this text contradicts — and the
 *  contradiction would be recorded, hashed, against every signup it collected. Changing the
 *  promise means a new `WAITLIST_CONSENT_VERSION` here AND in `WaitlistService`, not new copy. */
export const WAITLIST_CONSENT_TEXT =
  'One email, only if a pack ships. No newsletter. Unsubscribe in one click.';

/** Must match `WaitlistService.CurrentConsentVersion` in the API. */
export const WAITLIST_CONSENT_VERSION = 'waitlist-2026-07-30';

type SubmitState = 'idle' | 'sending' | 'queued' | 'error';

export interface WaitlistFormProps {
  /** Which placement collected this address. Stored verbatim on the signup row, so the two
   *  placements stay tellable apart without a second analytics event. */
  source: string;
  /** What they were searching for, when the placement has one. Omitted (not empty-stringed) on
   *  placements with no search behind them — the API nulls a blank query anyway, and an empty
   *  string in the column would read as "searched for nothing" rather than "never searched". */
  query?: string;
  submitLabel?: string;
}

/**
 * The consent box is **unticked by default** and the submit is refused without it, client-side
 * here and server-side in `WaitlistService`. A pre-ticked box is not consent under UK GDPR, and
 * the italic sentence under the form is the exact text the server hashes as evidence.
 */
export function WaitlistForm({ source, query, submitLabel = 'Put it in the queue' }: WaitlistFormProps) {
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
        source,
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
      <p className="text-sm leading-relaxed text-muted">
        <span className="font-bold text-text">You&apos;re in the queue.</span> We&apos;ll email you from
        support@mumchimp.com {query ? 'if a pack in this space survives the six checks' : 'if a new pack survives the six checks'}. Nothing else.
      </p>
    );
  }

  return (
    <>
      <form onSubmit={submit} className="flex max-w-md flex-col gap-3">
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
          label="Email me if a pack survives"
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
        />
        <Button type="submit" variant="prominent" disabled={state === 'sending'}>
          {state === 'sending' ? 'Adding you…' : submitLabel}
        </Button>
      </form>

      <p className="mt-3 text-xs italic text-muted">{WAITLIST_CONSENT_TEXT}</p>
    </>
  );
}
