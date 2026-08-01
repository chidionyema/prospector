import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { API_BASE_URL, LEGAL } from '@/lib/config';
import { fetchOrderBySession, type SessionOrderItem } from '@/lib/api/client';
import { PostPurchaseAccountNote } from '@/components/checkout/BuyerIdentityNote';
import { track } from '@/lib/analytics';

// The buyer lands here the instant the payment provider redirects, which is normally BEFORE
// the fulfilment webhook has been processed. So "not ready yet" is the expected first answer
// and we poll rather than treat it as failure.
const POLL_INTERVAL_MS = 2000;
// ~24s. Was 20 (~40s), which was tuned for a webhook delay we have never actually observed —
// Stripe delivers effectively instantly after payment. The long ceiling only ever prolonged the
// cases that were never going to resolve, and those now end the poll immediately on their own
// (see 'unfulfilled'/'revoked' below) rather than waiting for it.
const MAX_POLL_ATTEMPTS = 12;

type Phase = 'resolving' | 'ready' | 'no-session' | 'timed-out' | 'unfulfilled' | 'revoked';

/** window.location.origin never changes for the life of the document, so there is nothing to
 *  subscribe to. useSyncExternalStore still needs a subscribe function; this one registers no
 *  listener and its unsubscribe is a no-op. */
const subscribeToNothing = () => () => {};

export default function OrderSuccess() {
  const { query, isReady } = useRouter();
  const packId = typeof query.pack === 'string' ? query.pack : null;
  const sessionId = typeof query.session_id === 'string' ? query.session_id : null;

  const [pollPhase, setPollPhase] = React.useState<Phase>('resolving');
  const [items, setItems] = React.useState<SessionOrderItem[]>([]);
  const [copied, setCopied] = React.useState(false);

  // Resolved after mount, never during SSR: reading window on the server would either throw or
  // bake the build machine's origin into the HTML and cause a hydration mismatch.
  // useSyncExternalStore is the supported way to read a browser value that differs between
  // server and client — the server snapshot is '' and React swaps in the real origin on
  // hydration, without a setState-in-effect and its extra render pass.
  const origin = React.useSyncExternalStore(
    subscribeToNothing,
    () => window.location.origin,
    () => '',
  );

  // "No session id in the URL" is a fact about the URL, not an outcome of polling, so it is
  // derived rather than stored. Storing it meant writing state from inside the polling effect
  // on the very first run, which cascades an extra render before anything is on screen.
  const phase: Phase = isReady && !sessionId ? 'no-session' : pollPhase;

  React.useEffect(() => {
    if (!isReady) return;
    if (!sessionId) return;

    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      attempts += 1;
      try {
        const result = await fetchOrderBySession(sessionId);
        if (cancelled) return;
        if (result.status === 'ready' && result.items.length > 0) {
          setItems(result.items);
          setPollPhase('ready');
          return;
        }
        // Terminal answers: nothing further is coming, so stop rather than spend the remaining
        // attempts implying something is still on its way. This is the whole point of the API
        // distinguishing them — a buyer who cannot be fulfilled gets their reference at once
        // instead of watching a spinner for the full timeout first.
        if (result.status === 'unfulfilled' || result.status === 'revoked') {
          setPollPhase(result.status);
          return;
        }
      } catch {
        // Network hiccup or the API is briefly unavailable. Keep polling — the buyer's
        // entitlement exists regardless of whether this particular request succeeded.
      }
      if (cancelled) return;
      if (attempts >= MAX_POLL_ATTEMPTS) {
        setPollPhase('timed-out');
        return;
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [isReady, sessionId]);

  // Count the purchase once the order actually resolved — not on page load, which also happens
  // on refresh and on redirects that never fulfil. Sending it again on a reload is harmless:
  // the checkout session id travels as the event's meta and the API deduplicates on it, so the
  // count stays honest without marking the buyer's browser. (It previously used a localStorage
  // flag; that stored data on the device without consent — see lib/analytics.ts.)
  React.useEffect(() => {
    if (phase === 'ready' && sessionId) {
      track('checkout_completed', sessionId);
    }
  }, [phase, sessionId]);

  return (
    <MarketingLayout>
      <Seo title="Order Confirmed – Mumchimp" />

      <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center bg-bg px-6 py-16">
        <div className="flex w-full max-w-2xl flex-col items-center text-center gap-8">
          <div className="w-16 h-16 rounded-full bg-success/10 flex items-center justify-center">
            <Icon name="check" size={32} className="text-success" />
          </div>

          <div className="space-y-3">
            <h1 className="text-3xl md:text-4xl font-black text-text tracking-tighter">
              Order confirmed
            </h1>
            <p className="text-lg text-text/70 max-w-md">
              {phase === 'ready'
                ? 'Your payment was received. Your download is ready below.'
                : phase === 'resolving'
                  ? 'Your payment was received. Preparing your download…'
                  : phase === 'revoked'
                    ? 'This order has been refunded, so its download is no longer active.'
                    : 'Your payment was received and your purchase is safe.'}
            </p>
          </div>

          {phase === 'ready' && (
            <div className="w-full max-w-sm flex flex-col gap-3">
              {items.map((item) => (
                <a
                  key={item.packId}
                  href={`${API_BASE_URL}${item.downloadPath}`}
                  className="inline-flex items-center justify-center gap-2 px-6 py-4 rounded-xl bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors shadow-lg shadow-primary/20"
                >
                  <Icon name="download" size={16} />
                  Download {item.packTitle}
                </a>
              ))}
              {/* No confirmation email is sent while MAILJET_API_KEY / MAILJET_API_SECRET are unset
                  in production, so this page is currently the buyer's ONLY route back to what they
                  paid for. Promising an inbox link we do not send is what turns a lost tab into a
                  refund. When Mailjet is configured, restore the "we emailed you a copy" line HERE. */}
              {items[0]?.orderPath && (
                <div className="rounded-xl border border-border bg-surface2 p-4 text-left">
                  <p className="text-sm font-semibold text-text">Save this link now</p>
                  <p className="mt-1 text-xs text-muted">
                    It is your permanent access link — it does not expire. Bookmark it or copy it
                    somewhere safe before closing this page.
                  </p>
                  <code className="mt-2 block break-all rounded-lg bg-bg px-3 py-2 font-mono text-[11px] text-text">
                    {origin}
                    {items[0].orderPath}
                  </code>
                  <button
                    type="button"
                    onClick={() => {
                      void navigator.clipboard?.writeText(`${origin}${items[0].orderPath}`);
                      setCopied(true);
                    }}
                    className="mt-2 text-xs font-semibold text-primary underline"
                  >
                    {copied ? 'Copied ✓' : 'Copy link'}
                  </button>
                  {/* The second route back, and the only one that survives losing the link above.
                      A guest gets told what an account would do for them AFTER they have paid,
                      never as a condition of paying. */}
                  <PostPurchaseAccountNote className="mt-3 border-t border-border pt-3 text-xs leading-relaxed text-muted" />
                </div>
              )}
            </div>
          )}

          {phase === 'resolving' && (
            <div className="bg-surface2 border border-border rounded-xl p-6 max-w-sm w-full text-left">
              <p className="text-sm font-semibold text-text">Confirming your payment</p>
              <p className="text-xs text-muted mt-1">
                This usually takes a few seconds. You can stay on this page — your download will
                appear here as soon as it is ready.
              </p>
            </div>
          )}

          {(phase === 'no-session' ||
            phase === 'timed-out' ||
            phase === 'unfulfilled' ||
            phase === 'revoked') && (
            <div className="bg-surface2 border border-border rounded-xl p-6 max-w-sm w-full text-left space-y-4">
              {/* Do NOT tell the buyer to check their inbox: no fulfilment email is sent while
                  the MAILJET_* secrets are unset. Sending them to an empty inbox loses the sale.
                  Give them the one reference that actually lets support find the order. */}
              <div className="flex items-start gap-3">
                <Icon name="shield" size={16} className="text-primary mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-text">
                    {phase === 'no-session'
                      ? 'No order found on this page'
                      : phase === 'revoked'
                        ? 'This order was refunded'
                        : 'Your purchase is safe'}
                  </p>
                  {/* Each of these is a genuinely different situation, and saying so is the
                      point. 'unfulfilled' in particular is not a timeout: we KNOW the pack did
                      not go out, so it promises a person rather than implying the page might
                      still come good. */}
                  <p className="text-xs text-muted mt-0.5">
                    {phase === 'unfulfilled'
                      ? 'Your payment went through, but this order did not release its download. That is our fault, not yours. Send us the reference below and we will get your pack to you — or refund you in full, whichever you prefer.'
                      : phase === 'revoked'
                        ? 'This order was refunded, so its download has been withdrawn. Nothing further is owed. If that is unexpected, send us the reference below.'
                        : phase === 'timed-out'
                          ? 'Payment went through, but we could not show your download here in time. Send us the reference below and we will get your pack to you straight away.'
                          : 'This page was opened without a checkout reference, so there is nothing to show. If you have paid, contact us with your payment receipt and we will sort it out.'}
                  </p>
                </div>
              </div>
              {sessionId && (
                <div>
                  <p className="text-xs font-semibold text-text">Your order reference</p>
                  <code className="mt-1 block break-all rounded-lg bg-bg px-3 py-2 font-mono text-[11px] text-text">
                    {sessionId}
                  </code>
                  {/* Telling someone to "send us the reference" and then leaving them to scroll,
                      select a 60-character opaque string and compose the mail themselves is
                      where a recoverable order quietly turns into a refund request. The
                      reference is already in the subject and body here, so it takes one tap and
                      arrives in a form support can actually search on. */}
                  <a
                    href={
                      `mailto:${LEGAL.supportEmail}` +
                      `?subject=${encodeURIComponent(`Order ${sessionId}`)}` +
                      `&body=${encodeURIComponent(
                        `My payment went through but I have not received my download.\n\nOrder reference: ${sessionId}\n`,
                      )}`
                    }
                    className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary/90"
                  >
                    <Icon name="mail" size={16} />
                    Email us about this order
                  </a>
                </div>
              )}
            </div>
          )}

          <div className="flex flex-col sm:flex-row gap-4 mt-2">
            <Link
              href="/"
              className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl border border-border text-sm font-semibold text-text hover:bg-surface2 transition-colors"
            >
              Browse more packs
            </Link>
            {packId && (
              <Link
                href={`/pack/${packId}`}
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl border border-border text-sm font-semibold text-text hover:bg-surface2 transition-colors"
              >
                Back to pack
              </Link>
            )}
          </div>

          <p className="text-xs text-muted max-w-xs">
            Need help with your order? Contact{' '}
            <a href={`mailto:${LEGAL.supportEmail}`} className="underline">
              {LEGAL.supportEmail}
            </a>
          </p>
        </div>
      </div>
    </MarketingLayout>
  );
}
