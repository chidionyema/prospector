import React, { useEffect, useRef, useState } from 'react';
import {
  EmbeddedCheckoutProvider,
  EmbeddedCheckout as StripeEmbeddedCheckout,
} from '@stripe/react-stripe-js';
import { getStripe } from '@/lib/stripe';
import { isStripeApiReachable } from '@/lib/stripeReachable';
import { Icon } from '@/components/ui';

/** How long Stripe gets to insert its iframe before we call the overlay dead. */
const MOUNT_DEADLINE_MS = 12000;

interface EmbeddedCheckoutPanelProps {
  /** Server-issued session secret. The component owns nothing about the payment beyond this. */
  clientSecret: string;
  /** Close and return to the pack. Stripe has no cancel_url in embedded mode, this is it. */
  onClose: () => void;
  /** Shown in the panel header so the buyer can see what they are paying for. */
  title: string;
  /**
   * The overlay cannot work in this browser, hand the buyer to hosted checkout.
   *
   * Fires on either of two independent signals: Stripe's API is unreachable (probe), or Stripe
   * never inserted its iframe within `MOUNT_DEADLINE_MS`. Optional so the component keeps its
   * previous behaviour where a caller has nothing to hand off to.
   */
  onUnreachable?: () => void;
}

/**
 * Stripe's embedded checkout, over the pack page.
 *
 * Card fields render in Stripe's own cross-origin iframe exactly as they do on the hosted page,
 * so the PAN never reaches our JS (SECURE-UI §3, PCI). What changes is only that the buyer keeps
 * the page they were reading: the hosted redirect drops them onto checkout.stripe.com with none
 * of the evidence that persuaded them still on screen, and every buyer who wants to re-check one
 * figure before paying has to leave checkout to do it.
 *
 * On success Stripe navigates the iframe's parent to the session's return_url, the same
 * /orders/success?session_id=... the hosted flow uses, so fulfilment, entitlement resolution
 * and the success page are entirely unchanged by this component.
 */
export function EmbeddedCheckoutPanel({
  clientSecret,
  onClose,
  title,
  onUnreachable,
}: EmbeddedCheckoutPanelProps) {
  const stripe = getStripe();
  const closeRef = useRef<HTMLButtonElement>(null);
  const mountRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  // Escape closes, and the background does not scroll underneath an open checkout. Both are
  // undone on unmount, a checkout that leaves the page permanently unscrollable after the
  // buyer backs out is worse than no overlay at all.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  // Two independent ways to notice the overlay will never work, either of which hands the buyer
  // to hosted checkout. Both are needed: the probe catches a browser that cannot reach Stripe's
  // API (the iframe DOES appear, then renders Stripe's own error), and the mount deadline
  // catches the overlay never appearing at all, blocked iframes, storage partitioning, an SDK
  // that threw. Whichever fires first wins; `handedOff` makes sure only one does.
  useEffect(() => {
    if (!onUnreachable) return;
    let handedOff = false;
    const handOff = () => {
      if (handedOff) return;
      handedOff = true;
      onUnreachable();
    };

    isStripeApiReachable().then((reachable) => {
      if (!reachable) handOff();
    });

    const deadline = setTimeout(() => {
      // Stripe mounts into our container as an iframe. Its presence is the only same-origin
      // evidence available that the SDK got as far as rendering something.
      if (!mountRef.current?.querySelector('iframe')) handOff();
    }, MOUNT_DEADLINE_MS);

    return () => {
      handedOff = true; // Unmounted: never redirect a buyer who has already closed the panel.
      clearTimeout(deadline);
    };
  }, [onUnreachable, clientSecret]);

  // Stripe mounts asynchronously, so without this the buyer clicks pay and gets an empty white
  // box for as long as the SDK takes, the single clunkiest moment in the purchase. The iframe
  // appearing is the only same-origin signal available (react-stripe-js exposes no ready
  // callback), so this tracks "Stripe has rendered something", not "the card fields are
  // interactive". It errs early rather than late: a skeleton that lingers past a usable form
  // would be worse than one that clears a fraction of a second before the fields paint.
  useEffect(() => {
    const node = mountRef.current;
    if (!node) return;
    if (node.querySelector('iframe')) return; // Remount of an already-mounted secret.
    setReady(false);
    const observer = new MutationObserver(() => {
      if (node.querySelector('iframe')) {
        setReady(true);
        observer.disconnect();
      }
    });
    observer.observe(node, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [clientSecret]);

  // The caller only opens this panel once the API has returned a client secret, which a provider
  // without Stripe.js configured can never produce. Guarding anyway: rendering the provider with
  // a null stripe promise throws inside the SDK, and a throw here is a lost sale.
  if (!stripe) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Checkout for ${title}`}
      className="fixed inset-0 z-70 flex items-start justify-center overflow-y-auto bg-text/40 p-4 backdrop-blur-sm sm:p-8"
    >
      <div className="w-full max-w-2xl rounded-md border border-border bg-surface shadow-2">
        <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
      <span className="text-caption font-bold uppercase tracking-widest text-muted">
              Secure checkout
            </span>
            <p className="truncate text-meta font-bold text-text">{title}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close checkout"
            className="shrink-0 rounded-md border border-border p-2 text-muted transition-colors hover:bg-bg hover:text-text"
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        <div className="relative p-2 sm:p-4" ref={mountRef}>
          {/* Overlaid, never a conditional around the provider: Stripe needs its container in the
              DOM to mount into, so swapping it out for a skeleton would stop the thing we are
              waiting for from ever happening. */}
          {!ready && (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-white">
              <span
                className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-text"
                aria-hidden="true"
              />
              <p className="text-caption font-medium text-muted" role="status">
                Loading secure card form…
              </p>
            </div>
          )}
          {/* Holds the panel open at roughly the card form's height while Stripe mounts, so the
              overlay does not snap from a thin strip to full size under the buyer's cursor. */}
          <div className={ready ? undefined : 'min-h-[420px]'}>
            {/* Keyed on the secret so a new session mounts a fresh Stripe instance. The SDK does
                not accept a changed clientSecret on an existing provider. */}
            <EmbeddedCheckoutProvider key={clientSecret} stripe={stripe} options={{ clientSecret }}>
              <StripeEmbeddedCheckout />
            </EmbeddedCheckoutProvider>
          </div>
        </div>
      </div>
    </div>
  );
}
