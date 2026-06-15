import React, { useState } from 'react';
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js';
import { getStripe } from '@/lib/stripe';
import { Button, Card, Money, ErrorState, Checkbox } from '@/components/ui';

interface FundingPanelProps {
  /** The non-refundable platform-fee PaymentIntent (charged immediately). */
  feeClientSecret: string;
  /** The auth-hold PaymentIntent (manual capture — your bank holds, we never capture until delivery). */
  holdClientSecret: string;
  feeAmountCents: number;
  heldAmountCents: number;
  currency: string;
  onFunded: () => void;
}

/**
 * Collects a card in a Stripe Element (cross-origin iframe — the PAN never enters our JS)
 * and confirms BOTH server-issued PaymentIntents: the platform fee, then the auth-hold.
 * 3DS challenges are handled inline by `confirmCardPayment`. The bounty does not lock here —
 * Stripe's `amount_capturable_updated` webhook locks it server-side once the hold confirms.
 */
export default function FundingPanel(props: FundingPanelProps) {
  const stripePromise = getStripe();
  if (!stripePromise) {
    return (
      <ErrorState message="Payments are not configured in this environment (no Stripe publishable key). Set NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY to fund a proposal." />
    );
  }
  return (
    <Elements stripe={stripePromise}>
      <CardForm {...props} />
    </Elements>
  );
}

function CardForm({
  feeClientSecret,
  holdClientSecret,
  feeAmountCents,
  heldAmountCents,
  currency,
  onFunded,
}: FundingPanelProps) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discretionAccepted, setDiscretionAccepted] = useState(false);

  const handlePay = async () => {
    if (!stripe || !elements || !discretionAccepted) return;
    const card = elements.getElement(CardElement);
    if (!card) return;

    setSubmitting(true);
    setError(null);

    // 1) Platform fee — immediate, non-refundable. 3DS handled inline.
    // We pass the card element directly to confirmCardPayment. Reusing a created PaymentMethod id 
    // for multiple intents without a Customer attachment is forbidden by Stripe (PCI/re-use guard).
    const fee = await stripe.confirmCardPayment(feeClientSecret, { 
      payment_method: { card: card } 
    });
    if (fee.error) {
      setError(fee.error.message || 'The platform fee could not be charged. No hold was placed; please try again.');
      setSubmitting(false);
      return;
    }

    // 2) Auth-hold — your bank holds these funds; we never capture until the intro is delivered.
    const hold = await stripe.confirmCardPayment(holdClientSecret, { 
      payment_method: { card: card } 
    });
    if (hold.error) {
      setError(
        hold.error.message ||
          'The hold could not be authorised. The platform fee will be reversed automatically. Please try again.',
      );
      setSubmitting(false);
      return;
    }

    // Both confirmed. The webhook now locks the bounty server-side.
    onFunded();
  };

  return (
    <Card>
      <div className="space-y-5">
        <div className="space-y-1">
          <h2 className="text-h2 font-semibold text-text">Card details</h2>
          <p className="text-small text-muted">
            Your card is entered directly with Stripe. It never touches our servers.
          </p>
        </div>

        <div className="rounded-md border border-border bg-surface px-3 py-3">
          <CardElement options={{ hidePostalCode: false }} />
        </div>

        {/* The money moment: a contained, faintly-pressed "vault" panel so the figures read as the
            most considered thing on the page (DS08 / premium pass). */}
        <dl className="space-y-2 rounded-lg border border-border/70 bg-bg px-4 py-3 text-small">
          <div className="flex items-center justify-between">
            <dt className="text-muted">Posting fee (charged now)</dt>
            <dd className="font-semibold tabular-nums text-text">
              <Money cents={feeAmountCents} currency={currency} />
            </dd>
          </div>
          <div className="flex items-center justify-between border-t border-border/50 pt-2">
            <dt className="text-muted">Reward (held by your bank)</dt>
            <dd className="text-h3 font-semibold tabular-nums text-text">
              <Money cents={heldAmountCents} currency={currency} />
            </dd>
          </div>
          {/* The release promise sits INSIDE the money panel: this is the moment of hesitation, and
              the escape hatch must be visible before the button, not below it. The 6-day figure is
              the UnclaimedExpiryOptions.WindowHours default (144h); change them together. */}
          <p className="text-caption text-muted border-t border-border/50 pt-2">
            The posting fee is the only charge today. The reward stays as a hold with your bank, and becomes a charge only if you approve an intro. If no connector takes up your request within 6 days, the hold is released automatically and we email you to confirm.
          </p>
        </dl>

        {error && <ErrorState message={error} />}

        <div className="rounded-lg border border-border bg-surface2 p-4">
          <Checkbox
            checked={discretionAccepted}
            onChange={(e) => setDiscretionAccepted(e.target.checked)}
            label={
              <span className="text-small">
                I understand that I am compensating a connector for their <strong>curation and professional fit</strong>, and no meeting is guaranteed.
              </span>
            }
          />
        </div>

        <Button 
          fullWidth 
          loading={submitting} 
          onClick={() => void handlePay()} 
          disabled={!discretionAccepted}
        >
          Pay fee &amp; place hold
        </Button>
        
        <p className="text-caption text-muted text-center italic">
          Your request will be curated by a connector with a verified identity. If they don&apos;t forward it, your bank releases the hold.
        </p>
      </div>
    </Card>
  );
}
