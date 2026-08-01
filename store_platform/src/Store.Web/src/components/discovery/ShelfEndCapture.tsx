import React, { useState } from 'react';

import { Button, Checkbox, Input } from '@/components/ui';
import { joinWaitlist } from '@/lib/api/client';

import { WAITLIST_CONSENT_TEXT, WAITLIST_CONSENT_VERSION } from './EmptyState';

/**
 * The "email me the next survivor" capture, placed AFTER the shelf.
 *
 * Placement is the whole design. The deployed site carries this offer as a band between the hero
 * and the first product card, which spends above-the-fold space — the space that decides whether
 * a buyer sees a product at all (the same rule the hero comment in `pages/index.tsx` states) — on
 * buyers who haven't yet seen anything worth an email address. Below the shelf the ask meets the
 * only audience it converts: someone who scrolled the whole catalogue and still wants more. That
 * buyer has a reason to leave an address; a buyer at the top has only friction.
 *
 * Consent mechanics are identical to `DiscoveryWaitlist` (unticked checkbox, exact consent
 * sentence rendered and hashed server-side) — the constants are imported so the text cannot
 * drift from what `WaitlistService` records as evidence. Only the copy, layout, and `source`
 * tag differ; `source` distinguishes shelf-end signups from empty-state signups in the ledger.
 */

type SubmitState = 'idle' | 'sending' | 'queued' | 'error';

export function ShelfEndCapture({ className }: { className?: string }) {
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
        query: '',
        source: 'homepage-shelf-end',
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
      <div className={className}>
        <div className="rounded-2xl border border-border bg-surface px-6 py-5">
          <p className="text-sm font-bold text-text">You&apos;re in the queue.</p>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            We&apos;ll email you from support@mumchimp.com when the next pack survives the six
            checks. Nothing else.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={className}>
      <div className="rounded-2xl border border-border bg-surface px-6 py-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="max-w-md">
            <h2 className="text-base font-black tracking-tight text-text">
              Seen the whole shelf? The next survivor can come to you.
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              Most ideas the engine vets die on the six checks. When one survives, we can send it —
              one email per survivor, nothing else.
            </p>
          </div>

          <form onSubmit={submit} className="flex w-full max-w-md flex-col gap-2.5">
            <div className="flex gap-2">
              <div className="flex-1">
                <Input
                  label="Email"
                  hideLabel
                  type="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  error={error ?? undefined}
                />
              </div>
              <Button type="submit" disabled={state === 'sending'}>
                {state === 'sending' ? 'Adding…' : 'Email me'}
              </Button>
            </div>
            <Checkbox
              label="Email me when a pack survives"
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
            />
            <p className="text-xs italic text-muted">{WAITLIST_CONSENT_TEXT}</p>
          </form>
        </div>
      </div>
    </div>
  );
}
