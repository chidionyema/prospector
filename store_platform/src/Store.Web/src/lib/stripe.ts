/**
 * Stripe.js loader, the ONLY place the publishable key is read.
 *
 * Card data NEVER touches our JS or servers (SECURE-UI §3, PCI): the key here only
 * boots Stripe Elements, which renders card fields in a cross-origin iframe and returns
 * a PaymentMethod id. We confirm the server-issued PaymentIntents with that id; the PAN
 * is never in our React state.
 *
 * `loadStripe` is memoised by the SDK, but we cache the promise too so a re-render never
 * re-downloads the script. Returns `null` when the key is absent (e.g. local dev without
 * Stripe) so funding screens can degrade to a clear "not configured" state instead of throwing.
 */
// `/pure`, not the default entry. The default entry injects the Stripe.js <script> one tick
// after the MODULE is imported, and `lib/checkout/usePackCheckout` imports `stripeConfigured`
// from here, so every marketing page pulled js.stripe.com plus the m.stripe.network fraud
// iframe, which polls. The pure entry has the same API and injects nothing until `loadStripe`
// is actually called, which only `EmbeddedCheckoutPanel` does.
// The TYPE comes from the package root (a type-only import emits no runtime code, so it cannot
// inject anything); the VALUE comes from `/pure`, which has no `Stripe` type export.
import type { Stripe } from '@stripe/stripe-js';
import { loadStripe } from '@stripe/stripe-js/pure';

const PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;

let cached: Promise<Stripe | null> | null = null;

export function getStripe(): Promise<Stripe | null> | null {
  if (!PUBLISHABLE_KEY) return null;
  if (!cached) cached = loadStripe(PUBLISHABLE_KEY);
  return cached;
}

/** True when a publishable key is configured, gate funding UI on this. */
export const stripeConfigured = Boolean(PUBLISHABLE_KEY);
