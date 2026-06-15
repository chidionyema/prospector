import React from 'react';
import Link from 'next/link';
import { Seo } from '@/components/Seo';

/**
 * 500. Shown when the server itself errors, so it stays deliberately minimal — no data fetching,
 * no app providers to depend on. The reassurance about funds matters most here: a server error on
 * a money surface must never read as "my hold is gone".
 */
export default function ServerError() {
  return (
    <>
      <Seo title="Something went wrong" noindex />
      <main className="flex min-h-screen items-center justify-center bg-bg px-6 font-sans text-text">
        <div className="max-w-md text-center">
          <p className="text-small font-semibold uppercase tracking-wide text-muted">500</p>
          <h1 className="mt-2 text-h1 font-semibold text-text">Something went wrong on our side</h1>
          <p className="mt-3 text-body text-muted">
            This is on us, not you. Your account and any funded request are unaffected. Please try
            again in a moment.
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
