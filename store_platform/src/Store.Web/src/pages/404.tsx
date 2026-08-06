import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses } from '@/components/ui';

/**
 * 404. Calm, on-brand, and a clear way back, a dead-end with no exit reads as "this place is
 * broken", off-key for a trusted store. Wrapped in the marketing chrome (nav + footer) so it stays
 * consistent with every other page and always offers a way onward. MarketingLayout is identity-blind
 * and fetches nothing, so this still renders identically whether the missing route was public or authed.
 */
export default function NotFound() {
  return (
    <MarketingLayout>
      <Seo title="Page not found" noindex />
      <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center px-6 py-16">
        <div className="max-w-md text-center">
          <p className="text-body font-semibold text-muted">404</p>
          <h1 className="mt-2 text-h1 font-semibold text-text">We couldn&apos;t find that page</h1>
          <p className="mt-3 text-body text-muted">
            The link may be old or mistyped. Nothing is wrong with your account.
          </p>
          <Link
            href="/"
            className={buttonClasses({ size: 'lg', className: 'mt-6' })}
          >
            Back to home
          </Link>
        </div>
      </div>
    </MarketingLayout>
  );
}
