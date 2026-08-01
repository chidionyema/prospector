import { describe, expect, it, vi } from 'vitest';
import { resolveStripeCheckout } from '../checkoutRoute';

const hosted = () => Promise.resolve('https://checkout.stripe.com/c/pay/hosted_123');

describe('resolveStripeCheckout', () => {
  it('uses the embedded surface when the session carries a client secret', async () => {
    const route = await resolveStripeCheckout({
      stripeConfigured: true,
      requestEmbedded: async () => ({ clientSecret: 'cs_test_secret', url: null }),
      requestHosted: hosted,
    });

    expect(route).toEqual({ kind: 'embedded', clientSecret: 'cs_test_secret' });
  });

  it('redirects when the server answered with a hosted URL instead', async () => {
    const route = await resolveStripeCheckout({
      stripeConfigured: true,
      requestEmbedded: async () => ({ clientSecret: null, url: 'https://checkout.stripe.com/c/pay/from_server' }),
      requestHosted: hosted,
    });

    expect(route).toEqual({ kind: 'redirect', url: 'https://checkout.stripe.com/c/pay/from_server' });
  });

  // The regression this whole module exists to prevent: a throw on the embedded request used to
  // escape the click handler and render "Checkout failed", forfeiting a completable sale.
  it('still completes the sale when the embedded request THROWS', async () => {
    const requestHosted = vi.fn(hosted);

    const route = await resolveStripeCheckout({
      stripeConfigured: true,
      requestEmbedded: async () => {
        throw new Error('502 Bad Gateway');
      },
      requestHosted,
    });

    expect(route).toEqual({ kind: 'redirect', url: 'https://checkout.stripe.com/c/pay/hosted_123' });
    expect(requestHosted).toHaveBeenCalledOnce();
  });

  it('falls back when the session has neither a secret nor a URL', async () => {
    const route = await resolveStripeCheckout({
      stripeConfigured: true,
      requestEmbedded: async () => ({ clientSecret: null, url: null }),
      requestHosted: hosted,
    });

    expect(route).toEqual({ kind: 'redirect', url: 'https://checkout.stripe.com/c/pay/hosted_123' });
  });

  // A missing publishable key must degrade the surface, never hide or break the buy button.
  it('skips embedded entirely, without calling it, when Stripe.js is not configured', async () => {
    const requestEmbedded = vi.fn(async () => ({ clientSecret: 'cs_never_used', url: null }));

    const route = await resolveStripeCheckout({
      stripeConfigured: false,
      requestEmbedded,
      requestHosted: hosted,
    });

    expect(route).toEqual({ kind: 'redirect', url: 'https://checkout.stripe.com/c/pay/hosted_123' });
    expect(requestEmbedded).not.toHaveBeenCalled();
  });
});
