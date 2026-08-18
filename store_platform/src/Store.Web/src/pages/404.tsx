import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses } from '@/components/ui';

/**
 * 404. Wrapped in the marketing chrome (nav + footer) so it stays consistent with every other page
 * and always offers a way onward. MarketingLayout is identity-blind and fetches nothing, so this
 * renders identically whether the missing route was public or authed.
 *
 * MASTER-BRIEF section 7 `Errors`: name what happened, offer the one action that fixes it. Errors do
 * not apologise and are never vague. Two sentences came out on that rule.
 *
 * "The link may be old or mistyped" is a guess offered as an explanation, and it puts the reader in
 * the wrong: neither half is something we know, and if the link is one of ours, it is our fault. The
 * page now says what is true, which is that the address does not exist here.
 *
 * "Nothing is wrong with your account" was reassurance about a problem nobody had thought of yet,
 * on a store that does not need an account to buy anything. Raising it is what makes a reader
 * wonder.
 *
 * ONE ACTION. The catalogue, not the home page. Someone who lands on a dead URL on this site was
 * looking for a pack, and the shelf is the page that either has it or proves it does not exist.
 */
export default function NotFound() {
  return (
    <MarketingLayout>
      <Seo title="Page not found" noindex />
      <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center px-6 py-16">
        <div className="max-w-md text-center">
          <p className="text-body font-semibold text-muted">404</p>
          <h1 className="mt-2 text-h1 font-semibold text-text">There is no page at this address</h1>
          <p className="mt-3 text-body text-muted">
            Every pack we have ever published is on the shelf, and it is searchable.
          </p>
          <Link
            href="/"
            className={buttonClasses({ size: 'lg', className: 'mt-6' })}
          >
            Search the catalogue
          </Link>
        </div>
      </div>
    </MarketingLayout>
  );
}
