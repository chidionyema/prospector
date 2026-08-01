import { describe, expect, it, vi } from 'vitest';
import { STRIPE_PROBE_URL, isStripeApiReachable } from '../stripeReachable';

describe('isStripeApiReachable', () => {
  it('reports reachable when the probe resolves', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ type: 'opaque' });
    await expect(isStripeApiReachable({ fetchImpl: fetchImpl as never })).resolves.toBe(true);
  });

  it("probes Stripe's API in no-cors mode, the only check that discriminates", async () => {
    // Cross-origin means every healthy answer is opaque, so the response is unreadable by
    // design: resolve-vs-throw IS the signal. A cors-mode probe would throw on a healthy
    // server too and bounce every buyer out of a working overlay.
    const fetchImpl = vi.fn().mockResolvedValue({ type: 'opaque' });
    await isStripeApiReachable({ fetchImpl: fetchImpl as never });
    expect(fetchImpl).toHaveBeenCalledWith(STRIPE_PROBE_URL, expect.objectContaining({ mode: 'no-cors' }));
    expect(STRIPE_PROBE_URL).toMatch(/^https:\/\/api\.stripe\.com\//);
  });

  it('reports unreachable when the probe throws', async () => {
    // The real-world shape: net::ERR_CERT_AUTHORITY_INVALID surfaces as a TypeError.
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(isStripeApiReachable({ fetchImpl: fetchImpl as never })).resolves.toBe(false);
  });

  it('reports unreachable when the probe never settles within the timeout', async () => {
    const fetchImpl = vi.fn(
      (_url: string, init?: { signal?: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    );
    await expect(
      isStripeApiReachable({ fetchImpl: fetchImpl as never, timeoutMs: 10 }),
    ).resolves.toBe(false);
  });

  it('fails safe, reports reachable when there is no fetch to probe with', async () => {
    // Never block a sale on the probe's own unavailability.
    // `delete globalThis.fetch` is a type error only because lib.dom declares `fetch` as
    // required. Narrowing the view of globalThis to one optional property says the same thing to
    // the compiler without suppressing it, a ts-expect-error here would also swallow any real
    // type error this line grew later.
    const globalWithFetch = globalThis as { fetch?: typeof globalThis.fetch };
    const original = globalWithFetch.fetch;
    delete globalWithFetch.fetch;
    try {
      await expect(isStripeApiReachable()).resolves.toBe(true);
    } finally {
      globalWithFetch.fetch = original;
    }
  });
});
