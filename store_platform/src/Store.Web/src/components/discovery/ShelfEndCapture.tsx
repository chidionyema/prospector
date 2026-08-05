import React from 'react';

import { WaitlistForm } from '@/components/waitlist/WaitlistForm';

/**
 * The "email me the next survivor" capture, placed AFTER the shelf.
 *
 * Placement is the whole design. The deployed site carries this offer as a band between the hero
 * and the first product card, which spends above-the-fold space, the space that decides whether
 * a buyer sees a product at all (the same rule the hero comment in `pages/index.tsx` states), on
 * buyers who haven't yet seen anything worth an email address. Below the shelf the ask meets the
 * only audience it converts: someone who scrolled the whole catalogue and still wants more. That
 * buyer has a reason to leave an address; a buyer at the top has only friction.
 *
 * This owns the surrounding copy and nothing else. The form, the consent sentence and the submit
 * are `WaitlistForm`, the two things a placement is allowed to vary are its copy and its
 * `source` tag, and the promise is deliberately not one of them: `WaitlistService` hashes
 * `consentText` as the evidence of what was agreed to, so a second hand-written sentence here
 * would produce a second hash for one promise. `source` is what keeps shelf-end signups tellable
 * apart from empty-state signups in the ledger.
 *
 * No `query` is passed. There is no search behind this placement, and the prop is omitted rather
 * than empty-stringed on purpose, a blank string in the column reads as "searched for nothing"
 * rather than "never searched".
 */
export function ShelfEndCapture({ className }: { className?: string }) {
  return (
    <div className={className}>
      <div className="border border-border bg-surface px-6 py-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="max-w-md">
            <h2 className="text-body font-black tracking-tight text-text">
              Seen the whole shelf? The next survivor can come to you.
            </h2>
            <p className="mt-1 text-meta leading-relaxed text-muted">
              Most ideas the engine vets die on the six checks. When one survives, we can send it,
              one email per survivor, nothing else.
            </p>
          </div>

          <div className="w-full max-w-md">
            <WaitlistForm source="homepage-shelf-end" submitLabel="Email me" />
          </div>
        </div>
      </div>
    </div>
  );
}
