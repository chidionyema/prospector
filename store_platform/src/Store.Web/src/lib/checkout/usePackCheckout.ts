import { useState } from 'react';
import { createEmbeddedCheckout, createStripeCheckout } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthContext';
import { resolveStripeCheckout } from '@/lib/checkoutRoute';
import { initPaddle, openPaddleCheckout, paddleConfigured } from '@/lib/paddle';
import { stripeConfigured } from '@/lib/stripe';

/** Everything the buy path needs about a pack, satisfied by both `Pack` and `PackDetails`. */
export interface PackCheckoutTarget {
  id: string;
  title: string;
  paymentProvider: string;
  providerPriceId: string;
}

/**
 * The single-pack buy path, in one place.
 *
 * This is a straight extraction from `pages/pack/[id].tsx`, moved without behaviour change so a
 * second buy surface (the shelf's Buy drawer) can run the SAME code rather than a copy of it.
 * The reason that matters more here than in ordinary refactors: the logic below is not general
 * engineering, it is three production incidents written down.
 *
 *  1. The buy button was once gated on `stripeConfigured`, which hid every buy button in
 *     production when the publishable key was left out of the web build args, a sales outage
 *     with no error anywhere. A missing key must degrade the SURFACE, never the sale, so the
 *     gate is `hasProvisionedPrice` and nothing else.
 *  2. `resolveStripeCheckout` owns "embedded is preferred but never required", including the
 *     case where the embedded attempt THROWS, which previously escaped and rendered "Checkout
 *     failed" over a sale that would have completed.
 *  3. A session that is issued and then cannot RENDER had no escape at all, and the buyer saw
 *     Stripe's own "cannot be reached" message with nowhere to go (LIVE_RAIL_SMOKE_TEST.md,
 *     2026-07-31). `handleUnreachable` is that escape.
 *
 * Two copies of this would mean the next such fix lands in one of them. Hence one hook, two
 * callers, and `checkoutRoute.test.ts` still covering the routing decision underneath it.
 */
export function usePackCheckout(pack: PackCheckoutTarget, preopenedSecret?: string | null) {
  const [checkingOut, setCheckingOut] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  /** What the caller has decided about the overlay, which is NOT the same question as whether it
   *  is open, see `clientSecret` below.
   *   - `undefined`: nothing decided yet, so a pre-opened session is free to win.
   *   - `null`: decided closed. Also every provider and build that pays through the hosted
   *     redirect instead; null is not "failed".
   *   - a string: this session is open. */
  const [checkoutSession, setCheckoutSession] = useState<string | null | undefined>(undefined);

  // Derived, not copied into state by an effect. `preopenedSecret` comes from a source that is
  // already a source of truth (the pack page reads it off the URL), so mirroring it into state
  // bought nothing and cost two things: a first paint with the overlay shut before the effect
  // ran, and a re-open bug waiting to happen, closing sets null, and an effect keyed on the
  // secret would put it straight back. The three-state above is what keeps "not decided yet"
  // distinguishable from "closed": only the former defers to the pre-opened value.
  const clientSecret = checkoutSession === undefined ? preopenedSecret ?? null : checkoutSession;
  const setClientSecret = setCheckoutSession;

  // Null for a guest, and that is a complete answer rather than a missing one, checkout carries
  // the address only when we already know it. Sending it locks the field at Stripe, which is what
  // keeps the order joined to this account (orders join on email alone).
  const { account } = useAuth();
  const buyerEmail = account?.email ?? null;

  const provider = pack.paymentProvider || 'paddle';

  const handleStripeCheckout = async () => {
    // Embedded is preferred but never required. Two separate reasons it may not happen, no
    // Stripe.js key in this build, or a server that answered with a hosted URL anyway, and
    // both land on exactly the redirect that existed before embedded checkout was added.
    // createStripeCheckout already refuses any URL that is not Stripe's hosted checkout.
    const route = await resolveStripeCheckout({
      stripeConfigured,
      requestEmbedded: () => createEmbeddedCheckout(pack.id, buyerEmail),
      requestHosted: () => createStripeCheckout(pack.id, buyerEmail),
    });

    if (route.kind === 'embedded') {
      setClientSecret(route.clientSecret);
      return;
    }
    window.location.href = route.url;
  };

  const buy = async () => {
    setCheckingOut(true);
    setCheckoutError(null);

    try {
      if (provider === 'stripe') {
        await handleStripeCheckout();
      } else {
        await initPaddle();
        openPaddleCheckout(pack.providerPriceId);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '';
      setCheckoutError(message || 'Checkout failed. Please try again.');
    } finally {
      setCheckingOut(false);
    }
  };

  /**
   * The overlay opened but cannot work in this browser, send the buyer to hosted checkout.
   *
   * A new hosted session is requested rather than reusing the embedded one: an embedded session
   * has no `url`, so there is nothing to redirect to. The panel closes first, so a hosted request
   * that itself fails leaves a visible error on the page instead of a frozen overlay.
   */
  const handleUnreachable = async () => {
    setClientSecret(null);
    try {
      window.location.href = await createStripeCheckout(pack.id, buyerEmail);
    } catch {
      setCheckoutError(
        'Checkout could not load in this browser. Please try another browser, or disable any ad or privacy blocker for this page.',
      );
    }
  };

  // Stripe checkout may be a server-issued redirect to Stripe's HOSTED page, which never boots
  // Stripe.js, so the publishable key has no bearing on whether a pack can be bought. Gate
  // instead on the one thing that must actually be true: the pack points at a real provisioned
  // price. See incident 1 in the module doc.
  const hasProvisionedPrice =
    typeof pack.providerPriceId === 'string' &&
    pack.providerPriceId.length > 0 &&
    !pack.providerPriceId.startsWith('price_stub');

  const canCheckout =
    (provider === 'stripe' && hasProvisionedPrice) ||
    (provider !== 'stripe' && paddleConfigured);

  return {
    checkingOut,
    checkoutError,
    clientSecret,
    canCheckout,
    provider,
    buy,
    handleUnreachable,
    /** Close the embedded overlay without abandoning the page. */
    closeOverlay: () => setClientSecret(null),
    /** Open the overlay on a session created out of band (see `lib/preopenedCheckout`). */
    openOverlay: (secret: string) => setClientSecret(secret),
  };
}
