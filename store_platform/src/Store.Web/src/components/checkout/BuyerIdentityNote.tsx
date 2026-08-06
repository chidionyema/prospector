import React from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/auth/AuthContext';
import { textLinkClass } from '@/components/ui';

/**
 * Who this purchase will be filed under, said BEFORE the buyer pays.
 *
 * An order carries an email address and no user id (`Order.BuyerEmail`; there is no UserId
 * column), so the address recorded at the payment provider is the only link between a purchase and
 * an account. That rule is invisible, and breaking it fails silently in both directions: a
 * signed-in customer who types a different address at Stripe gets a valid order that never appears
 * in their account, and a guest who uses an address they cannot open loses the only durable route
 * back to what they paid for. Nobody sees an error in either case.
 *
 * Guest checkout is a supported path, not a degraded one, neither checkout route requires
 * authorization (CheckoutEndpoints.cs:24,40). So this does not nag a guest to sign in; it tells
 * them the one thing that is actually true and actionable about their address.
 */
export function BuyerIdentityNote({ className }: { className?: string }) {
  const { status, account } = useAuth();

  // 'loading' renders nothing rather than assuming "guest". The session probe resolves in well
  // under a second, and a line that says "checking out as a guest" and then contradicts itself is
  // worse than one that arrives a moment late.
  if (status === 'loading') return null;

  return (
    <p className={className ?? 'text-caption text-muted'}>
      {account ? (
        <>
          Buying as <strong className="font-semibold text-text">{account.email}</strong>, that
          address is locked at the payment step, so this purchase lands in your account.
          {!account.email_confirmed && ' Confirm the address to see it there.'}
        </>
      ) : (
        <>
          {/* Deliberately promises no email. No fulfilment mail is sent while the MAILJET_*
              secrets are unset (see orders/success.tsx:146-149), so "check your inbox" would be a
              lie that turns a completed sale into a refund. The permanent link on the success
              page is the guest's real route back, and an account is the second one. */}
          Checking out as a guest, no account needed. Your download appears straight after
          payment, on a permanent link. Use an address you can open:{' '}
          <Link href="/account?mode=register" className={textLinkClass()}>
            creating an account
          </Link>{' '}
          with the same one later brings this purchase with it.
        </>
      )}
    </p>
  );
}

/**
 * The same rule stated AFTER payment, on the confirmation page, where the two kinds of buyer need
 * genuinely different things.
 *
 * A signed-in buyer needs to know a second route exists so a lost tab is not a lost pack. A guest
 * needs to know the address they just typed is the one that will surface this order, the success
 * page already presses them to save the permanent link, and this is the durable alternative to it.
 */
export function PostPurchaseAccountNote({ className }: { className?: string }) {
  const { status, account } = useAuth();

  if (status === 'loading') return null;

  return (
    <p className={className ?? 'text-caption text-muted'}>
      {account ? (
        account.email_confirmed ? (
          <>
            This order is also in{' '}
            <Link href="/account" className={textLinkClass()}>
              your account
            </Link>
            , as long as you paid with <strong className="font-semibold text-text">{account.email}</strong>.
          </>
        ) : (
          <>
            Confirm <strong className="font-semibold text-text">{account.email}</strong> in{' '}
            <Link href="/account" className={textLinkClass()}>
              your account
            </Link>{' '}
            and this order appears there too. Until then the link above is your only route back.
          </>
        )
      ) : (
        <>
          Bought as a guest.{' '}
          <Link href="/account?mode=register" className={textLinkClass()}>
            Create an account
          </Link>{' '}
          with the email address you just paid with and this order, and any other you have made
          with it, shows up there permanently.
        </>
      )}
    </p>
  );
}
