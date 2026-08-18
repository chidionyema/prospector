import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Button, Card, Checkbox, Input, textLinkClass } from '@/components/ui';
import { SocialSignIn } from '@/components/account/SocialSignIn';
import { useAuth } from '@/lib/auth/AuthContext';
import { auth, AuthError } from '@/lib/api/auth';
import { TOS_VERSION } from '@/lib/config';

/**
 * Everything a signed-out visitor can do, on one route.
 *
 * The store has five auth journeys, sign in, register, forgot password, verify an address, reset
 * a password, and the-introduction-exchange gave each its own page. Four of those five are dead
 * ends: a customer who has just verified their address is looking at a page whose only remaining
 * purpose is to link them to the sign-in page. Collapsing them into one panel means every journey
 * ENDS on the form that finishes the job, with the address already filled in.
 *
 * The mode is explicit in the URL (`?verify=1`, `?reset=1`), never inferred from which parameters
 * happen to be present, so adding a future flow that also carries a `token` cannot silently
 * reroute an existing one. EmailTemplates.cs builds both links.
 */
type Mode = 'signin' | 'register' | 'forgot' | 'verifying' | 'reset';

interface AuthPanelProps {
  /** Parsed from the query string by the page, the panel does no routing of its own. */
  initial: {
    mode: Mode;
    userId?: string;
    email?: string;
    token?: string;
    /** An error code handed back by the API's OAuth callback redirect. */
    error?: string;
  };
  /** Absolute URL a social provider should return to. */
  returnTo: string;
}

const OAUTH_ERRORS: Record<string, string> = {
  'Auth.EmailNotVerified':
    'Your provider has not verified that email address, so we cannot use it to sign you in. Verify it with them, or use a password below.',
  'Auth.UnknownProvider': 'That sign-in provider is not available.',
  'Auth.ExternalLoginFailed': 'The provider did not complete the sign-in. Nothing was changed.',
  'Auth.InvalidExchangeCode': 'That sign-in link had already been used. Please try again.',
};

/** A verify link that lost half of itself in an email client is treated exactly like an expired
 *  one, same message, same recovery, rather than spinning on "Confirming…" forever. */
const BAD_VERIFY_LINK =
  'That verification link is invalid or has expired. Enter your email below and we will send a new one.';

export function AuthPanel({ initial, returnTo }: AuthPanelProps) {
  const { signIn } = useAuth();
  const canVerify = initial.mode === 'verifying' && Boolean(initial.userId) && Boolean(initial.token);
  const brokenVerifyLink = initial.mode === 'verifying' && !canVerify;

  const [mode, setMode] = useState<Mode>(brokenVerifyLink ? 'forgot' : initial.mode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(
    initial.error
      ? OAUTH_ERRORS[initial.error] ?? 'Sign-in did not complete. Please try again.'
      : brokenVerifyLink
        ? BAD_VERIFY_LINK
        : null,
  );
  const [notice, setNotice] = useState<string | null>(null);

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState(initial.email ?? '');
  const [password, setPassword] = useState('');
  const [tos, setTos] = useState(false);

  const fail = useCallback((err: unknown, fallback: string) => {
    setError(err instanceof AuthError ? err.message : fallback);
  }, []);

  // Verification runs on arrival, not on a button: the customer already clicked the button, it
  // was in the email. Asking them to click a second one to confirm the first is friction with no
  // security value, because possession of the link is the whole proof.
  useEffect(() => {
    if (!canVerify) return;
    let cancelled = false;
    // No setBusy here: 'verifying' renders its own full-panel "Confirming your email address…"
    // state, so there is nothing for a busy flag to disable. Every state change below happens in
    // the promise continuation, which is what react-hooks/set-state-in-effect asks for.
    auth
      .verifyEmail(initial.userId as string, initial.token as string)
      .then(() => {
        if (cancelled) return;
        setNotice('Your email address is verified. Sign in to see your account.');
        setMode('signin');
      })
      .catch(() => {
        if (cancelled) return;
        // The API answers a bad user id and a bad token identically, on purpose, a distinct
        // message would reveal which addresses have accounts. Offer the resend instead.
        setError(BAD_VERIFY_LINK);
        setMode('forgot');
      });
    return () => {
      cancelled = true;
    };
  }, [canVerify, initial.userId, initial.token]);

  const onSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username || email, password);
    } catch (err) {
      // One message for a wrong password, an unknown account and an unverified address alike,
      // the API returns the same Auth.InvalidCredentials for all three so the form cannot be used
      // to discover which addresses are registered.
      fail(err, 'Could not sign you in. Check your details and try again.');
      setBusy(false);
    }
  };

  const onRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.register(username, email, password, TOS_VERSION);
      // No sign-in here, and no token to sign in WITH: the API withholds one until the address is
      // confirmed, because orders are matched to an account by email address alone.
      setNotice(`Check ${email} for a link to confirm your address. You can sign in once it is confirmed.`);
      setMode('signin');
      setPassword('');
    } catch (err) {
      fail(err, 'Could not create the account.');
    } finally {
      setBusy(false);
    }
  };

  const onForgot = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Both of these always succeed, whether or not the address is registered. Sending them
      // together means one message covers "reset my password" and "resend my verification"
      // without the panel, or an attacker, learning which of the two applied.
      await Promise.all([
        auth.forgotPassword(email).catch(() => undefined),
        auth.resendVerification(email).catch(() => undefined),
      ]);
      setNotice(`If ${email} has an account, we have emailed it a link. Check the inbox.`);
      setMode('signin');
    } finally {
      setBusy(false);
    }
  };

  const onReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!initial.token || !initial.email) return;
    setBusy(true);
    setError(null);
    try {
      await auth.resetPassword(initial.email, initial.token, password);
      setNotice('Password changed. Sign in with your new password.');
      setPassword('');
      setMode('signin');
    } catch (err) {
      fail(err, 'That reset link is invalid or has expired. Request a new one below.');
    } finally {
      setBusy(false);
    }
  };

  const switchTo = (next: Mode) => {
    setMode(next);
    setError(null);
    setNotice(null);
  };

  if (mode === 'verifying') {
    return (
      <Card className="p-8 text-center">
        <p className="lede">Confirming your email address…</p>
      </Card>
    );
  }

  return (
    <Card className="p-6 sm:p-8">
      {notice && (
        <p className="mb-5 rounded-md border border-success bg-success/5 px-4 py-3 text-body text-text" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="mb-5 rounded-md border border-danger bg-danger/5 px-4 py-3 text-body text-text" role="alert">
          {error}
        </p>
      )}

      {mode === 'signin' && (
        <>
          <SocialSignIn returnTo={returnTo} />
          <form onSubmit={onSignIn} className="space-y-4">
            <Input
              label="Email or username"
              type="text"
              autoComplete="username"
              required
              value={username || email}
              onChange={(e) => {
                setUsername(e.target.value);
                setEmail(e.target.value);
              }}
            />
            <Input
              label="Password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Button type="submit" fullWidth loading={busy}>
              Sign in
            </Button>
          </form>
          <div className="mt-5 flex items-center justify-between text-caption">
            <Button variant="ghost" onClick={() => switchTo('forgot')}>
              Forgot password?
            </Button>
            <Button variant="ghost" onClick={() => switchTo('register')}>
              Create an account
            </Button>
          </div>
        </>
      )}

      {mode === 'register' && (
        <>
          <SocialSignIn returnTo={returnTo} />
          <form onSubmit={onRegister} className="space-y-4">
            <Input
              label="Email"
              hint="Use the address you bought with, and your past orders will appear here."
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Input
              label="Username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <Input
              label="Password"
              hint="At least 8 characters."
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Checkbox
              label={
                <>
                  I agree to the <Link href="/terms" className={textLinkClass()}>terms</Link> and{' '}
                  <Link href="/privacy" className={textLinkClass()}>privacy policy</Link>.
                </>
              }
              checked={tos}
              required
              onChange={(e) => setTos(e.target.checked)}
            />
            <Button type="submit" fullWidth loading={busy} disabled={!tos}>
              Create account
            </Button>
          </form>
          <div className="mt-5 text-caption">
            <Button variant="ghost" onClick={() => switchTo('signin')}>
              Already have an account? Sign in
            </Button>
          </div>
        </>
      )}

      {mode === 'forgot' && (
        <form onSubmit={onForgot} className="space-y-4">
          <Input
            label="Email"
            hint="We will send a link to reset your password or confirm your address."
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button type="submit" fullWidth loading={busy}>
            Email me a link
          </Button>
          <Button variant="ghost" fullWidth onClick={() => switchTo('signin')}>
            Back to sign in
          </Button>
        </form>
      )}

      {mode === 'reset' && (
        <form onSubmit={onReset} className="space-y-4">
          <Input label="Email" type="email" value={initial.email ?? ''} readOnly disabled />
          <Input
            label="New password"
            hint="At least 8 characters."
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" fullWidth loading={busy}>
            Set new password
          </Button>
        </form>
      )}
    </Card>
  );
}
