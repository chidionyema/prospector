import React from 'react';

import { WaitlistForm } from './WaitlistForm';

/**
 * The waitlist as a standing offer rather than a consolation prize.
 *
 * Before this it existed in exactly one place: the catalogue-wide empty state, which a visitor
 * only reaches by searching for something no pack covers. That is the honest moment to ask, but
 * it is also a moment almost nobody arrives at, so the one place we can lawfully keep in touch
 * with an interested reader was, in practice, unreachable.
 *
 * It sits BELOW the buy CTA on the sample report, deliberately. Someone who just read a whole
 * free dossier and wants a pack should buy one; the address is the second-best outcome, so it
 * gets the second position. Nothing here is gated, the sample stays free, and the hero's
 * "No payment, no email" promise has to remain true after this component exists.
 */
export function WaitlistCallout() {
  return (
    <div className="mt-6 border border-border bg-surface p-8 text-left md:p-10">
      <h3 className="text-lg font-black tracking-tight text-text">
        Nothing on the shelf for your space yet?
      </h3>
      {/* No subscriber count and no cadence. We have neither to honestly claim, and the consent
          text this form sends says "No newsletter", copy implying a regular send would contradict
          the very sentence being hashed as evidence one line below it. */}
      <p className="mt-2 max-w-[62ch] text-sm leading-relaxed text-muted">
        The catalogue grows only when an idea clears all six checks, so it grows slowly and
        unpredictably. Leave an address and we&apos;ll tell you when the next one does. That is the
        whole offer, no drip sequence, no pitch.
      </p>
      <div className="mt-5">
        <WaitlistForm source="sample-report-footer" submitLabel="Tell me when one survives" />
      </div>
    </div>
  );
}
