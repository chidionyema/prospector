/**
 * Mount the embedded checkout from a session created out of band.
 *
 * Why this exists: the overlay is the one layer no API call can prove. Stripe.js accepts a
 * malformed publishable key and only fails once Elements paints, and `resolveStripeCheckout`
 * falls back to hosted only when the session REQUEST fails — never when the render is wrong. The
 * proof is a human watching it paint against the LIVE key. This lets that happen on a session
 * priced by the API's smoke-test override, so seeing the form does not cost the listed price.
 *
 * Why a client secret in the URL is not a leak: a Checkout Session client secret is *designed* to
 * be handed to the browser — it is what Stripe.js receives on the ordinary path too. It is
 * single-use, expires, and Stripe binds it to the account behind our publishable key, so a
 * secret from another account cannot be made to render here. Nothing privileged crosses the
 * boundary: the internal API key that authorises the cheap price stays server-side, and the only
 * thing that reaches the browser is the same value a normal buy click would have produced.
 *
 * The shape check below is not a security control — Stripe enforces the real one. It exists so a
 * mistyped parameter fails as an ignored URL rather than as an SDK exception on a page a real
 * buyer might be looking at.
 */

/** Query parameter carrying a pre-created Checkout Session client secret. */
export const PREOPENED_CHECKOUT_PARAM = 'checkout_session';

/**
 * The secret half is a percent-encoded blob, NOT a plain token: a real live secret contains `%`
 * sequences (`…YCc%2FJ2Fg…`). An `[A-Za-z0-9_-]` charset looks obviously right and rejects every
 * genuine secret, so the parameter would be silently ignored and the overlay would never open.
 * Verified against a real 418-character live secret, whose only non-alphanumeric character is `%`.
 * The remaining unreserved URL characters are allowed so a future encoding change cannot
 * reintroduce the same silent rejection.
 */
const CLIENT_SECRET_SHAPE = /^cs_(?:live|test)_[A-Za-z0-9]+_secret_[A-Za-z0-9%._~-]+$/;

/**
 * Build the URL that opens this session on a pack page.
 *
 * Encoding is load-bearing and easy to get wrong by hand. The secret contains literal `%2F`
 * sequences; pasted raw into a query string the browser decodes them to `/`, handing Stripe a
 * DIFFERENT string than it issued and failing the session for a reason that looks like a broken
 * overlay. `encodeURIComponent` escapes the `%` itself (`%2F` -> `%252F`) so the value that
 * arrives back through `router.query` is byte-for-byte the secret Stripe issued.
 */
export function preopenedCheckoutUrl(origin: string, packId: string, clientSecret: string): string {
  const base = origin.replace(/\/+$/, '');
  return `${base}/pack/${encodeURIComponent(packId)}`
    + `?${PREOPENED_CHECKOUT_PARAM}=${encodeURIComponent(clientSecret)}`;
}

/**
 * The client secret to open on load, or null when the URL carries none usable.
 *
 * @param raw the raw query value (Next gives `string | string[] | undefined`)
 */
export function preopenedClientSecret(raw: string | string[] | undefined): string | null {
  // A repeated parameter is a malformed URL, not a choice to make on the buyer's behalf.
  if (typeof raw !== 'string') return null;

  const value = raw.trim();
  return CLIENT_SECRET_SHAPE.test(value) ? value : null;
}
