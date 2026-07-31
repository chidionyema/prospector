import React, { useEffect, useRef } from 'react';
import {
  EmbeddedCheckoutProvider,
  EmbeddedCheckout as StripeEmbeddedCheckout,
} from '@stripe/react-stripe-js';
import { getStripe } from '@/lib/stripe';
import { Icon } from '@/components/ui';

interface EmbeddedCheckoutPanelProps {
  /** Server-issued session secret. The component owns nothing about the payment beyond this. */
  clientSecret: string;
  /** Close and return to the pack. Stripe has no cancel_url in embedded mode — this is it. */
  onClose: () => void;
  /** Shown in the panel header so the buyer can see what they are paying for. */
  title: string;
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
 * On success Stripe navigates the iframe's parent to the session's return_url — the same
 * /orders/success?session_id=... the hosted flow uses — so fulfilment, entitlement resolution
 * and the success page are entirely unchanged by this component.
 */
export function EmbeddedCheckoutPanel({ clientSecret, onClose, title }: EmbeddedCheckoutPanelProps) {
  const stripe = getStripe();
  const closeRef = useRef<HTMLButtonElement>(null);

  // Escape closes, and the background does not scroll underneath an open checkout. Both are
  // undone on unmount — a checkout that leaves the page permanently unscrollable after the
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

  // The caller only opens this panel once the API has returned a client secret, which a provider
  // without Stripe.js configured can never produce. Guarding anyway: rendering the provider with
  // a null stripe promise throws inside the SDK, and a throw here is a lost sale.
  if (!stripe) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Checkout for ${title}`}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-text/40 p-4 backdrop-blur-sm sm:p-8"
    >
      <div className="w-full max-w-2xl rounded-2xl border border-border bg-white shadow-[0_24px_60px_rgba(0,0,0,0.24)]">
        <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted">
              Secure checkout
            </span>
            <p className="truncate text-sm font-bold text-text">{title}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close checkout"
            className="shrink-0 rounded-lg border border-border p-2 text-muted transition-colors hover:bg-bg hover:text-text"
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        <div className="p-2 sm:p-4">
          {/* Keyed on the secret so a new session mounts a fresh Stripe instance. The SDK does
              not accept a changed clientSecret on an existing provider. */}
          <EmbeddedCheckoutProvider key={clientSecret} stripe={stripe} options={{ clientSecret }}>
            <StripeEmbeddedCheckout />
          </EmbeddedCheckoutProvider>
        </div>
      </div>
    </div>
  );
}
