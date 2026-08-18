import React from 'react';

import { cx } from '@/components/ui/cx';
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
    /* THE DRAWING'S EMAIL BOX (`mockups/index.html:553`, section 14). This was a two-column card:
       heading and lede on the left, a stacked form on the right. The drawing runs it as one
       block -- `h2.sec`, the sentence, the field and the button on one row, then the fine print
       -- so the ask reads top to bottom instead of across. Founder, 2026-08-18: use the mockup's
       version. The copy and the consent mechanism are unchanged. */
    <section className={cx('emailbox', className)}>
      {/* THE PROMISE, ONCE. This block stated it four times over three elements: the heading,
          both halves of the body, and the submit label. Four restatements of one offer read as
          persuasion, which is the register this pass removes.

          The unsubscribe line is deliberately NOT repeated here. `WaitlistForm` renders
          `WAITLIST_CONSENT_TEXT` directly under the field and `WaitlistService` hashes that exact
          string as the evidence of what the subscriber agreed to, so a second promise written
          here would be a fifth telling AND a second hash for one consent.

          §6.1 of docs/SITE_SPEC_PROGRAM.md asks for the microcopy "Unsubscribe any time." That
          promise IS rendered, once, as the last clause of `WAITLIST_CONSENT_TEXT` ("Unsubscribe
          in one click"). Rewording it is not a copy edit: the string is SHA-256'd into every
          stored signup and its `WAITLIST_CONSENT_VERSION` is pinned to
          `WaitlistService.CurrentConsentVersion` in the API, so changing the words needs a
          version bump deployed on both sides, not an edit here. */}
      <h2 className="sec">The next survivor can come to you.</h2>
      <p>
        Most ideas die in the filter. When one survives, you get one email. That’s the whole list.
      </p>
      {/* No `submitLabel` override, 2026-08-14: the homepage carried two email forms whose buttons
          named the same action two different ways. One action, one verb, set in `WaitlistForm` and
          inherited everywhere, so a third placement cannot invent a fourth wording. */}
      <WaitlistForm source="homepage-shelf-end" inline />
    </section>
  );
}
