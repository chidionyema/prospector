import React, { useState } from 'react';

import { Button, Checkbox, Input } from '@/components/ui';
import { joinWaitlist } from '@/lib/api/client';
import { LEGAL } from '@/lib/config';

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
 *  A placement that implies a regular send is making a promise this text contradicts, and the
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
   *  placements with no search behind them, the API nulls a blank query anyway, and an empty
   *  string in the column would read as "searched for nothing" rather than "never searched". */
  query?: string;
  submitLabel?: string;
  /**
   * The drawing's shape (`mockups/index.html:556`): the field and the button on ONE row, the
   * consent under them as fine print. The default stacked form is kept for the narrow placements
   * (the empty state, the sidebar) where a 470px row would wrap anyway.
   *
   * The consent checkbox is rendered in BOTH shapes. The drawing does not show one, but the box
   * is unticked by default and the submit is refused without it here and in `WaitlistService`;
   * a pre-ticked or absent box is not consent under UK GDPR. Layout does not get to decide that.
   */
  inline?: boolean;
}

/**
 * The consent box is **unticked by default** and the submit is refused without it, client-side
 * here and server-side in `WaitlistService`. A pre-ticked box is not consent under UK GDPR, and
 * the italic sentence under the form is the exact text the server hashes as evidence.
 */
export function WaitlistForm({ source, query, submitLabel = 'Put it in the queue', inline }: WaitlistFormProps) {
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
      setError('We could not add you to the list. Try again in a moment.');
      setState('error');
    }
  };

  if (state === 'queued') {
    return (
      <p className="lede">
        <span className="font-semibold text-text">You&apos;re in the queue.</span> We&apos;ll email you from{' '}
        {LEGAL.supportEmail} {query ? 'if a pack in this space is listed' : 'if a new pack is listed'}. Nothing else.
      </p>
    );
  }

  const field = (
    <Input
      label="Email"
      type="email"
      required
      value={email}
      onChange={(event) => setEmail(event.target.value)}
      placeholder="you@example.com"
      error={error ?? undefined}
    />
  );
  const box = (
    <Checkbox
      label="Email me if a pack is listed"
      checked={consent}
      onChange={(event) => setConsent(event.target.checked)}
    />
  );
  const send = (
    <Button type="submit" variant="primary" disabled={state === 'sending'}>
      {state === 'sending' ? 'Adding you…' : submitLabel}
    </Button>
  );

  if (inline) {
    /*
     * THE DRAWING'S FORM (`mockups/index.html:556`): one row holding a bare input and a `.btn`,
     * then the promise as fine print under it.
     *
     * It renders plain elements rather than `Input` and `Button` because the styled components
     * could not be made to look like the drawing. Their utility classes sit in Tailwind's
     * `utilities` layer; mumchimp.css is imported into `components`, which loses to it. So
     * `.emailbox input` (height 46, paper ground, 15px type) was overruled on every declaration
     * it made, and the box rendered as a Tailwind control inside a hand-drawn card. Plain
     * elements hand the drawing's stylesheet back the control it is supposed to have.
     *
     * The consent box stays and it IS the fine line now, rather than a second control stacked
     * above it. Its label is `WAITLIST_CONSENT_TEXT` itself, so what the reader ticks and what
     * `WaitlistService` hashes are the same sentence, and the row still reads as one line of
     * fine print the way the drawing does.
     */
    return (
      <form onSubmit={submit}>
        <input
          type="email"
          aria-label="Email address"
          placeholder="you@example.com"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <button className="btn" type="submit" disabled={state === 'sending'}>
          {state === 'sending' ? 'Adding you\u2026' : submitLabel}
        </button>
        <label className="fine consent">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
          />
          <span>{WAITLIST_CONSENT_TEXT}</span>
        </label>
        {error && (
          <p className="fine err" role="alert">
            {error}
          </p>
        )}
      </form>
    );
  }

  return (
    <>
      <form onSubmit={submit} className="flex max-w-md flex-col gap-3">
        {field}
        {box}
        {send}
      </form>

      <p className="mt-3 text-caption italic text-muted">{WAITLIST_CONSENT_TEXT}</p>
    </>
  );
}
