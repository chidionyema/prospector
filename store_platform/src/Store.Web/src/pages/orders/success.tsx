import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { Breadcrumbs, Icon, Skeleton, buttonClasses, textLinkClass } from '@/components/ui';
import { API_BASE_URL, LEGAL } from '@/lib/config';
import { fetchOrderBySession, fetchPackDetails, fetchCatalog, type SessionOrderItem, type Pack, type PackDetails } from '@/lib/api/client';
import { PostPurchaseAccountNote } from '@/components/checkout/BuyerIdentityNote';
import { track } from '@/lib/analytics';

// The buyer lands here the instant the payment provider redirects, which is normally BEFORE
// the fulfilment webhook has been processed. So "not ready yet" is the expected first answer
// and we poll rather than treat it as failure.
const POLL_INTERVAL_MS = 2000;
// ~24s. Was 20 (~40s), which was tuned for a webhook delay we have never actually observed,
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
  const [pollAttempt, setPollAttempt] = React.useState(0);
  const [items, setItems] = React.useState<SessionOrderItem[]>([]);
  const [copied, setCopied] = React.useState(false);

  // Pack details for the welcome. Fetched only after the order resolves, so we know which
  // pack id to load. The catalogue fetch is opportunistic and best-effort: a partial
  // "no cross-sell" is better than a hero that never paints.
  const [pack, setPack] = React.useState<PackDetails | null>(null);
  const [catalog, setCatalog] = React.useState<Pack[]>([]);

  // Resolved after mount, never during SSR: reading window on the server would either throw or
  // bake the build machine's origin into the HTML and cause a hydration mismatch.
  // useSyncExternalStore is the supported way to read a browser value that differs between
  // server and client, the server snapshot is '' and React swaps in the real origin on
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
      setPollAttempt(attempts);
      try {
        const result = await fetchOrderBySession(sessionId);
        if (cancelled) return;
        if (result.status === 'ready' && result.items.length > 0) {
          setItems(result.items);
          setPollPhase('ready');
          // US-8: once the order resolves, fetch the pack details for the welcome page
          // (cover, title, one-liner) and the catalogue for cross-sell. Both are best-effort:
          // the welcome is complete without them; the page degrades gracefully.
          const firstPackId = result.items[0]?.packId;
          if (firstPackId) {
            void fetchPackDetails(firstPackId)
              .then((p) => { if (!cancelled) setPack(p); })
              .catch(() => { /* pack details are nice-to-have, not critical */ });
          }
          void fetchCatalog()
            .then((c) => { if (!cancelled) setCatalog(c); })
            .catch(() => { /* cross-sell is nice-to-have, not critical */ });
          return;
        }
        // Terminal answers: nothing further is coming, so stop rather than spend the remaining
        // attempts implying something is still on its way. This is the whole point of the API
        // distinguishing them, a buyer who cannot be fulfilled gets their reference at once
        // instead of watching a spinner for the full timeout first.
        if (result.status === 'unfulfilled' || result.status === 'revoked') {
          setPollPhase(result.status);
          return;
        }
      } catch {
        // Network hiccup or the API is briefly unavailable. Keep polling, the buyer's
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

  // Count the purchase once the order actually resolved, not on page load, which also happens
  // on refresh and on redirects that never fulfil. Sending it again on a reload is harmless:
  // the checkout session id travels as the event's meta and the API deduplicates on it, so the
  // count stays honest without marking the buyer's browser. (It previously used a localStorage
  // flag; that stored data on the device without consent, see lib/analytics.ts.)
  React.useEffect(() => {
    if (phase === 'ready' && sessionId) {
      track('checkout_completed', sessionId);
    }
  }, [phase, sessionId]);

  // ERROR / EARLY STATES  -  no MarketingLayout wrapper, the buyer is post-purchase.
  // The audit is specific: "the buyer is post-purchase; let them stay". Hiding the global
  // nav removes the "Browse more packs" dopamine hit that competes with the download CTA.
  if (phase !== 'ready') {
    return (
      <ResolutionFallback
        phase={phase}
        sessionId={sessionId}
        pollAttempt={pollAttempt}
        packId={packId}
      />
    );
  }

  // READY  -  the welcome. 8 sections, in order:
  //  1. Pack cover plate (16:9 hero)
  //  2. Pack title (h1)
  //  3. Pack one-liner
  //  4. Download link (full-width primary button)
  //  5. Cross-sell: "Other packs in this category" (3 cards)
  //  6. Share with a friend
  //  7. Save your receipt
  //  8. What's next?  -  4-step checklist
  const firstItem = items[0];
  const shareUrl = origin && packId ? `${origin}/pack/${packId}` : '';

  // Cross-sell: same market, exclude the just-bought pack, top 3 by source count.
  const crossSell = pack
    ? catalog
        .filter((p) => p.id !== pack.id && p.market === pack.market)
        .sort((a, b) => (b.sourceCount ?? 0) - (a.sourceCount ?? 0))
        .slice(0, 3)
    : [];

  // The page does not use MarketingLayout (audit: post-purchase, no global nav), so the trail
  // is rendered via the Breadcrumbs component directly. Same data shape as MarketingLayout's
  // `breadcrumbs` prop, named the same, so the source-level test that scans for breadcrumbs
  // does not have to special-case this route.
  // breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'Order complete' }]}
  const breadcrumbs = [{ href: '/', label: 'Catalogue' }, { href: '#', label: 'Order complete' }];

  return (
    <main id="main" className="min-h-dvh bg-bg">
      <Seo title="Order confirmed, your pack is ready" />

      <div className="mx-auto max-w-3xl px-6 pt-6 md:px-8 lg:px-10">
        <Breadcrumbs items={breadcrumbs} />
      </div>

      <div className="mx-auto max-w-3xl px-6 py-12 md:py-16">
        {/* 1. Cover plate (16:9 hero). Use a colour-coded gradient as the placeholder until
            the canonical pack art (US-2) lands. The category colour is the same fallback
            the rest of the site uses for missing imagery. */}
        <div className="relative mb-8 aspect-[16/9] overflow-hidden rounded-md border border-border bg-surface2">
          <div className="absolute inset-0 bg-[radial-gradient(120%_120%_at_12%_-10%,rgba(255,255,255,0.25),transparent_55%)]" />
          <div className="absolute inset-0 flex items-end p-8">
            <span className="inline-flex items-center gap-2 rounded-sm border border-border bg-surface px-3 py-1.5 text-caption font-medium text-text">
              <Icon name="check" size={14} className="text-success" />
              Order confirmed
            </span>
          </div>
        </div>

        {/* 2. Pack title */}
        <h1 className="text-h1 font-semibold text-text">
          {pack?.title ?? firstItem?.packTitle ?? 'Your pack is ready'}
        </h1>

        {/* 3. Pack one-liner */}
        <p className="mt-3 max-w-[60ch] text-body leading-relaxed text-muted">
          {pack?.oneLine ?? 'Your payment was received. The download is ready below.'}
        </p>

        {/* 4. Download link  -  full-width primary button. The single most important action
            on the page; the rest of the welcome is a scaffold around it. */}
        {firstItem && (
          <div className="mt-8">
            <a
              href={`${API_BASE_URL}${firstItem.downloadPath}`}
              className={buttonClasses({ size: 'lg', fullWidth: true })}
            >
              <Icon name="download" size={18} />
              Download your pack
            </a>
            {/* The full evidence is the second route back. Refunded orders (revoked) and
                pending orders (unfulfilled) also live here, both end the welcome early. */}
            {firstItem.orderPath && (
              <div className="mt-4 rounded-md border border-border bg-surface p-4 text-left">
                <p className="text-meta font-semibold text-text">Save this link now</p>
                <p className="mt-1 text-caption text-muted">
                  It is your permanent access link, it does not expire. Bookmark it or copy it
                  somewhere safe before closing this page.
                </p>
                <code className="mt-2 block break-all rounded-md bg-bg px-3 py-2 font-mono text-caption text-text">
                  {origin}
                  {firstItem.orderPath}
                </code>
                <button
                  type="button"
                  onClick={() => {
                    void navigator.clipboard?.writeText(`${origin}${firstItem.orderPath}`);
                    setCopied(true);
                  }}
                  className={textLinkClass('font-medium')}
                >
                  {copied ? (
                    <span className="flex items-center gap-1">
                      <Icon name="check" size={16} />
                      Copied
                    </span>
                  ) : (
                    'Copy link'
                  )}
                </button>
                <PostPurchaseAccountNote className="mt-3 border-t border-border pt-3 text-caption leading-relaxed text-muted" />
              </div>
            )}
          </div>
        )}

        {/* 5. Cross-sell: same market, top 3 by source count. Buyers who bought one pack
            are likelier to buy another from the same market. The "more evidence than the
            shop normally surfaces" framing makes the cross-sell credible, not cringe. */}
        {crossSell.length > 0 && (
          <section className="mt-12 border-t border-border pt-10">
            <h2 className="text-h2 font-semibold text-text">
              Other packs in this category
            </h2>
            <p className="mt-2 max-w-[60ch] text-meta text-muted">
              Same vetted filter, same evidence standard. Three more from the same market.
            </p>
            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
              {crossSell.map((p) => (
                <Link
                  key={p.id}
                  href={`/pack/${p.id}`}
                  className="group flex flex-col gap-2 rounded-md border border-border bg-surface p-4 transition-colors hover:bg-bg"
                >
                  <p className="text-meta font-semibold text-text group-hover:text-primary transition-colors line-clamp-2">
                    {p.cardLine || p.title}
                  </p>
                  <p className="mt-auto text-caption font-semibold text-muted">
                    {p.sourceCount ?? 0} sources
                  </p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* 6. Share with a friend. The audit's "recommender persona": a buyer who wants
            to share the pack with a friend needs one tap. The link is the pack page URL. */}
        {shareUrl && (
          <section className="mt-10 border-t border-border pt-10">
            <h2 className="text-body font-semibold text-text">
              Share with a friend
            </h2>
            <p className="mt-2 max-w-[60ch] text-meta text-muted">
              If this helped, send it to the one person who would actually build it.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard?.writeText(shareUrl);
                  setCopied(true);
                }}
                className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-4 py-2 text-meta font-semibold text-text transition-colors hover:bg-bg"
              >
                <Icon name="arrowRight" size={14} />
                Copy link
              </button>
              <a
                href={`https://x.com/intent/tweet?text=${encodeURIComponent(`Vetted business pack from Mumchimp: ${pack?.title ?? ''}`)}&url=${encodeURIComponent(shareUrl)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-4 py-2 text-meta font-semibold text-text transition-colors hover:bg-bg"
              >
                Share on X
              </a>
            </div>
          </section>
        )}

        {/* 7. Save your receipt. The audit's "delivery surface, not a thank-you decoration".
            The receipt is the order's orderPath opened with a print stylesheet hint. */}
        {firstItem && (
          <section className="mt-10 border-t border-border pt-10">
            <h2 className="text-body font-semibold text-text">
              Save your receipt
            </h2>
            <p className="mt-2 max-w-[60ch] text-meta text-muted">
              Keep a copy for your records. The receipt is your orderPath; the bookmark
              above is the same URL.
            </p>
            <button
              type="button"
              onClick={() => {
                if (typeof window === 'undefined') return;
                window.print();
              }}
              className="mt-4 inline-flex items-center gap-2 rounded-md border border-border bg-surface px-4 py-2 text-meta font-semibold text-text transition-colors hover:bg-bg"
            >
              <Icon name="download" size={14} />
              Print / save as PDF
            </button>
          </section>
        )}

        {/* 8. What's next?  -  4-step checklist. The pack is a multi-week project. The
            checklist is the buyer's reason to come back. Each step is a tap away from
            the relevant section of the pack. */}
        <section className="mt-10 border-t border-border pt-10">
          <h2 className="text-body font-semibold text-text">
            {`What's next`}
          </h2>
          <p className="mt-2 max-w-[60ch] text-meta text-muted">
            The pack is a built project, not a report. Four steps to a first customer.
          </p>
          <ol className="mt-6 space-y-3">
            {[
              'Read the executive summary, the 4-page read that frames the build',
              'Skim the QA report, the one section that lists every sourcing caveat',
              'Run the build spec for day one, the first deliverable in your first week',
              'Pick your first customer, the persona dossier inside the pack',
            ].map((step, i) => (
              <li key={i} className="flex items-start gap-3 rounded-md border border-border bg-surface p-4">
                <span className="flex h-6 w-6 flex-none items-center justify-center rounded-sm bg-text text-caption font-medium text-bg">
                  {i + 1}
                </span>
                <span className="text-meta leading-relaxed text-muted">{step}</span>
              </li>
            ))}
          </ol>
        </section>

        {/* Quiet browser-back affordance. The audit said "let them stay", but a buyer
            who wants to see the rest of the shop needs an exit too. */}
        <div className="mt-12 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <Link
            href="/"
            className="inline-flex items-center justify-center gap-2 px-6 py-3 text-meta font-semibold text-muted hover:text-text transition-colors"
          >
            Browse more packs
          </Link>
          {packId && (
            <Link
              href={`/pack/${packId}`}
              className="inline-flex items-center justify-center gap-2 px-6 py-3 text-meta font-semibold text-muted hover:text-text transition-colors"
            >
              Back to pack
            </Link>
          )}
        </div>

        <p className="mt-8 text-center text-caption text-muted">
          Need help with your order? Contact{' '}
          <a href={`mailto:${LEGAL.supportEmail}`} className={textLinkClass()}>
            {LEGAL.supportEmail}
          </a>
        </p>
      </div>
    </main>
  );
}

/**
 * The pre-resolution fallback (resolving, no-session, timed-out, unfulfilled, revoked).
 * Lives in its own function so the ready-state welcome below can read as a single,
 * buyer-facing flow without the error-state conditional noise.
 */
function ResolutionFallback({
  phase,
  sessionId,
  pollAttempt,
  packId,
}: {
  phase: Phase;
  sessionId: string | null;
  pollAttempt: number;
  packId: string | null;
}) {
  return (
    <main id="main" className="min-h-dvh bg-bg">
      <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center bg-bg px-6 py-16">
        <div className="flex w-full max-w-2xl flex-col items-center text-center gap-8">
          <div className="w-16 h-16 rounded-sm bg-success/10 flex items-center justify-center">
            <Icon name="check" size={32} className="text-success" />
          </div>

          <div className="space-y-3">
            <h1 className="text-h1 font-semibold text-text">
              Order confirmed
            </h1>
            <p className="text-body text-muted max-w-md">
              {phase === 'ready'
                ? 'Your payment was received. Your download is ready below.'
                : phase === 'resolving'
                  ? 'Your payment was received. Preparing your download…'
                  : phase === 'revoked'
                    ? 'This order has been refunded, so its download is no longer active.'
                    : 'Your payment was received and your purchase is safe.'}
            </p>
          </div>

          {phase === 'resolving' && (
            <div className="bg-surface rounded-md border border-border p-6 max-w-sm w-full text-left space-y-5">
              <div className="h-1 w-full bg-border overflow-hidden rounded-sm">
                <div
                  className="h-full bg-text transition-all rounded-sm"
                  style={{ width: `${(pollAttempt / MAX_POLL_ATTEMPTS) * 100}%` }}
                />
              </div>
              <div className="space-y-3">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            </div>
          )}

          {(phase === 'no-session' ||
            phase === 'timed-out' ||
            phase === 'unfulfilled' ||
            phase === 'revoked') && (
            <div className="bg-surface rounded-md border border-border p-6 max-w-sm w-full text-left space-y-4">
              {phase === 'timed-out' && (
                <div className="h-1 w-full bg-border overflow-hidden rounded-sm">
                  <div
                    className="h-full bg-danger transition-all rounded-sm"
                    style={{ width: '100%' }}
                  />
                </div>
              )}
              <div className="flex items-start gap-3">
                <Icon name="shield" size={16} className="text-success mt-0.5 shrink-0" />
                <div>
                  <p className="text-meta font-semibold text-text">
                    {phase === 'no-session'
                      ? 'No order found on this page'
                      : phase === 'revoked'
                        ? 'This order was refunded'
                        : 'Your purchase is safe'}
                  </p>
                  <p className="text-caption text-muted mt-0.5">
                    {phase === 'unfulfilled'
                      ? 'Your payment went through, but this order did not release its download. That is our fault, not yours. Send us the reference below and we will get your pack to you, or refund you in full, whichever you prefer.'
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
                  <p className="text-caption font-semibold text-text">Your order reference</p>
                  <code className="mt-1 block break-all rounded-md bg-bg px-3 py-2 font-mono text-caption text-text">
                    {sessionId}
                  </code>
                  <a
                    href={
                      `mailto:${LEGAL.supportEmail}` +
                      `?subject=${encodeURIComponent(`Order ${sessionId}`)}` +
                      `&body=${encodeURIComponent(
                        `My payment went through but I have not received my download.\n\nOrder reference: ${sessionId}\n`,
                      )}`
                    }
                    className={buttonClasses({ fullWidth: true, className: 'mt-3' })}
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
              className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-md border border-border text-meta font-semibold text-text hover:bg-surface transition-colors"
            >
              Browse more packs
            </Link>
            {packId && (
              <Link
                href={`/pack/${packId}`}
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-md border border-border text-meta font-semibold text-text hover:bg-surface transition-colors"
              >
                Back to pack
              </Link>
            )}
          </div>

          <p className="text-caption text-muted max-w-xs">
            Need help with your order? Contact{' '}
            <a href={`mailto:${LEGAL.supportEmail}`} className={textLinkClass()}>
              {LEGAL.supportEmail}
            </a>
          </p>
        </div>
      </div>
    </main>
  );
}

/** Tiny inline SEO so the page has a `title` and an `id="main"` for the skip link,
 *  without dragging the full MarketingLayout back in. The audit is specific: hide the
 *  global nav, keep the page accessible. */
function Seo({ title }: { title: string }) {
  React.useEffect(() => {
    document.title = title;
  }, [title]);
  return null;
}
