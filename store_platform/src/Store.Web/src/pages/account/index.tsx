import React, { useMemo } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHeader, Skeleton } from '@/components/ui';
import { AuthPanel } from '@/components/account/AuthPanel';
import { AccountPanel } from '@/components/account/AccountPanel';
import { ReturnBlocks } from '@/components/account/ReturnBlocks';
import { useAuth } from '@/lib/auth/AuthContext';

/**
 * The whole customer-account surface: one route.
 *
 * Signed out it is sign-in / register / forgot-password, and, via the query string the
 * transactional emails carry, verify-address and reset-password. Signed in it is orders, details
 * and security. The-introduction-exchange spread the same functionality over nine pages; the
 * storefront has one kind of user and one thing they come here to do, which is get at what they
 * bought.
 *
 * noindex, and not because the content is secret, a signed-out crawler only ever sees a sign-in
 * form. It is that a sign-in form indexed against the store's name outranks the catalogue for
 * people searching the brand.
 */
export default function AccountPage() {
  const router = useRouter();
  const { status } = useAuth();

  const initial = useMemo(() => {
    const q = router.query;
    const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

    if (one(q.verify) === '1') {
      return {
        mode: 'verifying' as const,
        userId: one(q.user_id),
        token: one(q.token),
        error: one(q.error),
      };
    }
    if (one(q.reset) === '1') {
      return {
        mode: 'reset' as const,
        email: one(q.email),
        token: one(q.token),
        error: one(q.error),
      };
    }
    return {
      mode: (one(q.mode) === 'register' ? 'register' : 'signin') as 'register' | 'signin',
      error: one(q.error),
    };
  }, [router.query]);

  // Absolute, because it leaves our origin: the API's open-redirect guard compares it against the
  // configured web base and falls back to /auth/callback if it does not match
  // (ExternalAuthEndpoints.cs:188). Computed in the browser so a preview deployment returns to
  // itself rather than to whatever host was baked in at build time.
  const returnTo = typeof window === 'undefined' ? '' : `${window.location.origin}/auth/callback`;

  return (
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'Your account' }]}
      breadcrumbsWidth="6xl"
    >
      <Head>
        <meta name="robots" content="noindex, nofollow" />
      </Head>
      {/* THE SHELL, NOT A THIRD ONE OF ITS OWN (2026-08-18, founder: "ensure the members
          account page has the same polish as the rest of the site").

          This was `max-w-3xl px-4 py-12 sm:px-6 lg:px-8`: a 768px column at three different
          gutters, none of them the 20px the header and footer use, on the one page a paying
          customer sees most. Against a 1080px header it read as a different site. It is now the
          same measure and the same gutter as every band on every other page.

          THE SIGNED-OUT FORM DOES NOT GET WIDER: `AuthPanel` is capped at `max-w-md` below, which
          is why that cap was put on the panel rather than on this wrapper in the first place. What
          the extra 312px is for is the SIGNED-IN branch -- owned packs, receipts and the shortlist
          are wide rows, and `mockups/account.html` draws them across the full wrap. */}
      <div className="mx-auto max-w-[1080px] px-5 pt-6 pb-16">
        <PageHeader
          title={status === 'authenticated' ? 'Your account' : 'Sign in'}
          description={
            status === 'authenticated'
              ? undefined
              : 'Your purchases are tied to the email address you bought with, sign in with it to see them.'
          }
        />

        {/* min-h-[400px]: CLS fix (measured 0.184 at 360px, first of two shift entries, ~710ms
            after navigation, GET /auth/me resolving in AuthContext.tsx). The three-line skeleton
            below is ~96px (h-8 + 2*h-4 + 2*16px space-y-4 gaps); either real branch that replaces
            it is taller, so the swap was a pure growth shift with nothing above it to absorb.
            400px is derived from the signed-out branch specifically (AuthPanel in its default
            'signin' mode, no notice/error banner), which is the branch a typical /account visit
            hits: Card padding 24+24 (mobile p-6) + 2px border + SocialSignIn's own now-reserved
            74px + the two-field form (2 * (label 25.6 + gap-1 4 + input h-10 40) + two 16px
            space-y-4 gaps = 211.2) + the "forgot / create account" row (mt-5 20 + h-10 40) =
            ~395px, rounded up. This is a computed derivation from the Tailwind tokens in
            globals.css, not a live Playwright measurement -- re-verify with the audit if the
            tokens change. It does NOT match the signed-in branch (AccountPanel, taller once an
            order or two renders), which still gets a smaller but non-zero residual shift; a
            min-height only ever raises a floor, it cannot force the taller branch to shrink. */}
        <div className="mt-8 min-h-[400px]">
          {/* Nothing renders until the session question is answered. The alternative shows every
              returning customer a sign-in form for one frame before their account replaces it. */}
          {status === 'loading' && (
            <div className="space-y-4">
              <Skeleton className="h-8 w-48" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          )}
          {/* THE FORM IS NOT A PAGE-WIDTH OBJECT. The wrapper is `max-w-3xl` because the SIGNED-IN
              branch needs it -- library cards and receipts are wide rows. The signed-out branch is
              two fields, and at that width it drew a 704px card holding a 638px email input
              (measured on prod at 1280 viewport, 2026-08-16), the widest input on the site by a
              factor of two, which reads as an unstyled form rather than a designed one. Capping
              the panel keeps its left edge flush with the heading, so the column still reads as
              one block. Capped HERE rather than on the wrapper so the authenticated branch is
              untouched and the session resolving cannot shift the layout sideways. */}
          {status === 'anonymous' && (
            <div className="max-w-md">
              <AuthPanel initial={initial} returnTo={returnTo} />
            </div>
          )}
          {status === 'authenticated' && <AccountPanel />}
        </div>

        {/* MASTER-BRIEF section 7 `/account`: owned packs with download links first (AccountPanel
            above, whose Orders tab opens on the library), shortlist second, new since your last
            visit third. Both of the last two are per-browser and render nothing when empty, so a
            new customer sees exactly the page they see today. */}
        {status === 'authenticated' && <ReturnBlocks />}
      </div>
    </MarketingLayout>
  );
}
