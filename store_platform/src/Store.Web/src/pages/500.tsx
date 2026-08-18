import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses } from '@/components/ui';

/**
 * 500. Shown when the server itself errors. Wrapped in the marketing chrome (nav + footer) for
 * consistency with the rest of the store; MarketingLayout fetches nothing and carries no providers,
 * so it stays safe on a failed render.
 *
 * MASTER-BRIEF section 7 `Errors`: name what happened, offer the one action that fixes it, do not
 * apologise, do not be vague.
 *
 * "Your account and any funded request are unaffected" is copy from a different product. This store
 * has no funded requests -- that is the-introduction-exchange's escrow language, carried over with
 * the layout -- so the one sentence written to reassure a buyer about their money named a thing
 * that does not exist here and left the thing that does, a payment, unmentioned.
 *
 * What a reader actually needs to know at a 500 is whether they have been charged. Stripe takes the
 * payment and issues the download, and neither is this server, so a failure here cannot take money.
 * That is a fact about the architecture, not a soothing noise, and it is the one worth printing.
 */
export default function ServerError() {
  return (
    <MarketingLayout>
      <Seo title="Something went wrong" noindex />
      <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center px-6 py-16">
        <div className="max-w-md text-center">
          <p className="text-body font-semibold text-muted">500</p>
          <h1 className="mt-2 text-h1 font-semibold text-text">This page failed to load</h1>
          <p className="mt-3 text-body text-muted">
            The fault is on our server, so nothing you did caused it. Payments and downloads are
            handled by Stripe and are not affected: if you were buying a pack, you have not been
            charged twice.
          </p>
          <Link
            href="/"
            className={buttonClasses({ size: 'lg', className: 'mt-6' })}
          >
            Reload the catalogue
          </Link>
        </div>
      </div>
    </MarketingLayout>
  );
}
