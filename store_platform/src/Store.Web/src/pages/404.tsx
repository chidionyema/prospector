import React from 'react';
import Link from 'next/link';
import { Seo } from '@/components/Seo';

/**
 * 404. Calm, on-brand, and a clear way back — a dead-end with no exit reads as "this place is
 * broken", off-key for a trusted private room. Self-contained (no app/marketing chrome) so it
 * renders identically whether the missing route was public or authed.
 */
export default function NotFound() {
  return (
    <>
      <Seo title="Page not found" noindex />
      <main className="flex min-h-screen items-center justify-center bg-bg px-6 font-sans text-text">
        <div className="max-w-md text-center">
          <p className="text-small font-semibold uppercase tracking-wide text-muted">404</p>
          <h1 className="mt-2 text-h1 font-semibold text-text">We couldn&apos;t find that page</h1>
          <p className="mt-3 text-body text-muted">
            The link may be old or mistyped. Nothing is wrong with your account.
          </p>
          <Link
            href="/"
            className="mt-6 inline-flex items-center justify-center rounded-sm bg-primary px-5 py-2.5 text-small font-semibold text-on-primary hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
          >
            Back to home
          </Link>
        </div>
      </main>
    </>
  );
}
