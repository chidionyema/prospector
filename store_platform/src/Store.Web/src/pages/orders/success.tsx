import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';

export default function OrderSuccess() {
  const { query } = useRouter();
  const packId = typeof query.pack === 'string' ? query.pack : null;

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
              Your payment was received. A download link is on its way to your inbox.
            </p>
          </div>

          <div className="bg-surface2 border border-border rounded-xl p-6 max-w-sm w-full text-left space-y-4">
            <div className="flex items-start gap-3">
              <Icon name="mail" size={16} className="text-primary mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-semibold text-text">Check your email</p>
                <p className="text-xs text-muted mt-0.5">
                  We have sent a magic download link to the email you used at checkout.
                  It may take a minute or two to arrive.
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
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors shadow-lg shadow-primary/20"
              >
                Back to pack
              </Link>
            )}
          </div>

          <p className="text-xs text-muted max-w-xs">
            Can&apos;t find the email? Check your spam folder or contact{' '}
            <a href="mailto:support@prospector.store" className="underline">
              support@prospector.store
            </a>
          </p>
        </div>
      </div>
    </MarketingLayout>
  );
}
