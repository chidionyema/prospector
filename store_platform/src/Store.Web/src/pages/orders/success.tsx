import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { API_BASE_URL, LEGAL } from '@/lib/config';
import { fetchOrderBySession, type SessionOrderItem } from '@/lib/api/client';

// The buyer lands here the instant the payment provider redirects, which is normally BEFORE
// the fulfilment webhook has been processed. So "not ready yet" is the expected first answer
// and we poll rather than treat it as failure.
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 20; // ~40s, then fall back to the email/support path.

type Phase = 'resolving' | 'ready' | 'no-session' | 'timed-out';

export default function OrderSuccess() {
  const { query, isReady } = useRouter();
  const packId = typeof query.pack === 'string' ? query.pack : null;
  const sessionId = typeof query.session_id === 'string' ? query.session_id : null;

  const [phase, setPhase] = React.useState<Phase>('resolving');
  const [items, setItems] = React.useState<SessionOrderItem[]>([]);

  React.useEffect(() => {
    if (!isReady) return;
    if (!sessionId) {
      setPhase('no-session');
      return;
    }

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
          setPhase('ready');
          return;
        }
      } catch {
        // Network hiccup or the API is briefly unavailable. Keep polling — the buyer's
        // entitlement exists regardless of whether this particular request succeeded.
      }
      if (cancelled) return;
      if (attempts >= MAX_POLL_ATTEMPTS) {
        setPhase('timed-out');
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

  return (
    <MarketingLayout>
      <Seo title="Order Confirmed – Prospector Store" />

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
                  : 'Your payment was received. A download link is on its way to your inbox.'}
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
              <p className="text-xs text-muted">
                We have also emailed you a personal link, so you can come back to this any time.
              </p>
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

          {(phase === 'no-session' || phase === 'timed-out') && (
            <div className="bg-surface2 border border-border rounded-xl p-6 max-w-sm w-full text-left space-y-4">
              <div className="flex items-start gap-3">
                <Icon name="mail" size={16} className="text-primary mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-text">Check your email</p>
                  <p className="text-xs text-muted mt-0.5">
                    {phase === 'timed-out'
                      ? 'This is taking longer than usual. Your purchase is safe and your link will arrive by email shortly.'
                      : 'We have sent a magic download link to the email you used at checkout. It may take a minute or two to arrive.'}
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <Icon name="shield" size={16} className="text-primary mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-text">Secure, expiring link</p>
                  <p className="text-xs text-muted mt-0.5">
                    The link is personal to you. Your pack is ready to download immediately.
                  </p>
                </div>
              </div>
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
