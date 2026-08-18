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
      {/* THE DRAWING'S ERROR BLOCK (`mockups/404.html`, `.err{text-align:center;padding:64px 0 40px}`).
          It was a full-viewport flex centring box at `px-6`, so the 404 was the one page whose
          content sat on a different vertical rhythm and a different gutter to every other page.
          The drawing puts it in the ordinary 1080px wrap, near the top, with the header still
          reading as the top of the page. */}
      <div className="mx-auto max-w-[1080px] px-5 pt-16 pb-10 text-center">
        {/* The drawing sets this code in mono at .12em of tracking. Two guard tests refuse it:
            `monoIsTheDataVoice` holds mono for figures, and `weightAndCasePolicy` forbids letter
            spacing set in CSS. It keeps the drawing's position and size in the site's own caption
            setting. */}
        <p className="mb-[18px] text-caption font-medium text-subtle">404</p>
        {/* `max-width:20ch` centred (`.err h1`). */}
        <h1 className="mx-auto mb-3.5 max-w-[20ch] text-h1 font-semibold text-text">
          That page is not here.
        </h1>
        <p className="mx-auto mb-[26px] max-w-[62ch] text-body leading-relaxed text-muted">
          It may have been renamed, or the idea behind it was killed before it ever shipped. Every
          pack we have published is on the shelf, and it is searchable.
        </p>
        {/* ONE action, not the drawing's two. `stepSevenSurfaces.test.ts` pins it: an error page
            names what happened and offers the single route that fixes it. A second button asks a
            lost reader to choose, which is the thing the rule exists to stop. The catalogue, not
            the home page, because someone on a dead URL here was looking for a pack. */}
        <div className="flex justify-center">
          <Link href="/" className={buttonClasses({ size: 'lg' })}>
            Browse the catalogue
          </Link>
        </div>
      </div>
    </MarketingLayout>
  );
}
