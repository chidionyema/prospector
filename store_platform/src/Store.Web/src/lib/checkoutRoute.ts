/**
 * Decide which Stripe surface a buy click should land on.
 *
 * This exists as a separate unit because the rule it encodes is a money-rail guarantee, and a
 * guarantee that lives inline in a click handler cannot be tested: EMBEDDED IS PREFERRED BUT
 * NEVER REQUIRED. Every way the embedded attempt can fail, a thrown request, a session with
 * neither a client secret nor a URL, or no publishable key in the build at all, must still end
 * on the hosted redirect that existed before embedded checkout was added.
 *
 * The failure that motivates the try/catch: gating or crashing the buy path on a surface
 * upgrade loses a sale the old path would have completed. A missing key, or a Stripe account
 * that cannot issue embedded sessions, must degrade the SURFACE, never the sale.
 */

export interface EmbeddedSession {
  clientSecret: string | null;
  url: string | null;
}

export type CheckoutRoute =
  | { kind: 'embedded'; clientSecret: string }
  | { kind: 'redirect'; url: string };

export interface CheckoutRouteOptions {
  /** False when the build carries no Stripe publishable key, skip embedded, never block. */
  stripeConfigured: boolean;
  requestEmbedded: () => Promise<EmbeddedSession>;
  requestHosted: () => Promise<string>;
}

export async function resolveStripeCheckout(
  { stripeConfigured, requestEmbedded, requestHosted }: CheckoutRouteOptions,
): Promise<CheckoutRoute> {
  if (stripeConfigured) {
    try {
      const session = await requestEmbedded();
      if (session.clientSecret) {
        return { kind: 'embedded', clientSecret: session.clientSecret };
      }
      if (session.url) {
        return { kind: 'redirect', url: session.url };
      }
      // Neither field set: not an error, just a provider that cannot do embedded. Fall through.
    } catch {
      // Deliberately swallowed. The hosted redirect below is the whole point of the fallback;
      // rethrowing here would surface "Checkout failed" for a sale that can still be completed.
    }
  }

  return { kind: 'redirect', url: await requestHosted() };
}
