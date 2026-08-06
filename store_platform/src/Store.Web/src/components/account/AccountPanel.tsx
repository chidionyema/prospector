import React, { useCallback, useEffect, useState } from 'react';
import { Button, Card, EmptyState, Input, Money, SegmentedControl, Skeleton, textLinkClass, useToast } from '@/components/ui';
import { useAuth } from '@/lib/auth/AuthContext';
import { auth, social, AuthError, type Order, type ProfileEdit, type Session } from '@/lib/api/auth';
import { API_BASE_URL } from '@/lib/config';

/**
 * Resolve the API's root-relative download path against the API origin.
 *
 * /download/{token} is served by the API and is NOT one of the paths next.config.ts proxies, so a
 * bare "/download/…" resolves against the STOREFRONT origin and 404s, the same trap already
 * recorded at pages/orders/[token].tsx:51-53, which this mirrors deliberately.
 *
 * Anything that is not an https URL or a single-leading-slash path is dropped rather than rendered.
 * The value arrives from the API, so this is defence in depth, not distrust of the current server:
 * `\/(?!\/)` is what rejects a protocol-relative "//evil.com", which the browser would treat as a
 * different host entirely.
 */
function downloadHref(path: string | null): string | undefined {
  if (!path) return undefined;
  if (/^https:\/\//.test(path)) return path;
  if (/^\/(?!\/)/.test(path)) return `${API_BASE_URL}${path}`;
  return undefined;
}

/**
 * The signed-in account: orders, details, security. One route, three tabs.
 *
 * Tabs rather than routes because all three are short and all three are read far more often than
 * written, a customer arriving to re-download something should not pay a navigation to find out
 * their orders are on a different page than the one the header linked to. The tab is local state,
 * not a URL segment, because nobody deep-links to their own security settings.
 */
type Tab = 'orders' | 'details' | 'security';

const TABS = [
  { value: 'orders', label: 'Orders' },
  { value: 'details', label: 'Details' },
  { value: 'security', label: 'Security' },
] as const;

export function AccountPanel() {
  const { account, signOut, refresh } = useAuth();
  const [tab, setTab] = useState<Tab>('orders');

  if (!account) return null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-body font-semibold text-text">
            {account.profile.display_name || account.username}
          </p>
          <p className="text-caption text-muted">{account.email}</p>
        </div>
        <Button variant="ghost" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>

      {!account.email_confirmed && (
        <Card className="border-warning p-4">
          <p className="text-body text-text">
            Confirm <strong>{account.email}</strong> to see your orders. Anyone can type an email
            address, so we only show a purchase history once the address is proven.
          </p>
          <div className="mt-3">
            <Button
              variant="secondary"
              onClick={() => void auth.resendVerification(account.email)}
            >
              Send the link again
            </Button>
          </div>
        </Card>
      )}

      <SegmentedControl<Tab>
        options={TABS.map((t) => ({ value: t.value, label: t.label }))}
        value={tab}
        onChange={setTab}
        ariaLabel="Account sections"
      />

      {tab === 'orders' && <OrdersTab />}
      {tab === 'details' && <DetailsTab onSaved={refresh} />}
      {tab === 'security' && <SecurityTab />}
    </div>
  );
}

function OrdersTab() {
  // Naming the address is the point of the empty state. Orders join to an account by email alone
  // (Order.BuyerEmail, no user id), so "no orders yet" is ambiguous in a way that costs a support
  // mail: it can equally mean "you bought as a guest under a different address". Showing which
  // address this list is of lets the customer answer that themselves.
  const { account } = useAuth();
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [confirmed, setConfirmed] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    auth
      .orders()
      .then((r) => {
        setConfirmed(r.email_confirmed);
        setOrders(r.orders);
      })
      .catch((err) => setError(err instanceof AuthError ? err.message : 'Could not load your orders.'));
  }, []);

  if (error) return <Card className="p-6"><p className="text-body text-text">{error}</p></Card>;
  if (!orders) return <Card className="p-6"><div className="space-y-3"><Skeleton className="h-5 w-3/4" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-2/3" /></div></Card>;

  if (!confirmed) {
    return (
      <EmptyState
        title="Orders are hidden until your address is confirmed"
        description="Your purchase history is tied to your email address, so we show it only once that address is verified."
      />
    );
  }

  if (orders.length === 0) {
    return (
      <EmptyState
        title="No orders yet"
        description={
          `This list is everything bought with ${account?.email ?? 'your email address'}, including ` +
          'guest purchases made before you created the account. If you paid under a different ' +
          'address, use the permanent link from that order, or contact us and we will move it.'
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      {orders.map((order) => (
        <Card key={order.id} className="p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-caption text-muted">
              {new Date(order.created_at).toLocaleDateString()} · {order.status}
            </p>
            <Money cents={order.amount_pence} currency={order.currency} />
          </div>
          <ul className="mt-4 space-y-3">
            {order.items.map((item) => (
              <li key={item.pack_id} className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-body text-text">{item.pack_title}</span>
                {downloadHref(item.download_path) ? (
                  // A plain anchor, not a fetch: /download/{token} answers with a 302 to a
                  // short-lived presigned URL, and the browser must follow it as a navigation.
                  <a
                    href={downloadHref(item.download_path)}
                    className={textLinkClass('font-medium')}
                  >
                    Download
                  </a>
                ) : (
                  <span className="text-caption text-muted">
                    {item.status === 'revoked' ? 'Refunded' : 'Unavailable'}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

function DetailsTab({ onSaved }: { onSaved: () => Promise<unknown> }) {
  const { account } = useAuth();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<ProfileEdit>(() => {
    const p = account!.profile;
    return {
      first_name: p.first_name,
      last_name: p.last_name,
      phone: p.phone,
      bio: p.bio,
      website: p.website,
      avatar_url: p.avatar_url,
      country: p.country,
    };
  });

  const set = useCallback(
    (key: keyof ProfileEdit) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [key]: e.target.value })),
    [],
  );

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // PUT is a full replace, so the whole form is always sent, a partial body would clear the
      // fields it omitted rather than leave them alone.
      await auth.updateProfile(form);
      await onSaved();
      toast('Details saved.', 'success');
    } catch (err) {
      // The API validates the website scheme and the country code; surface its message rather
      // than a generic one, because it names the field that was rejected.
      setError(err instanceof AuthError ? err.message : 'Could not save your details.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-6">
      <form onSubmit={onSubmit} className="space-y-4">
        {error && (
          <p className="rounded-md border border-danger bg-danger/5 px-4 py-3 text-body text-text" role="alert">
            {error}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="First name" value={form.first_name} onChange={set('first_name')} />
          <Input label="Last name" value={form.last_name} onChange={set('last_name')} />
        </div>
        <Input label="Phone" type="tel" value={form.phone} onChange={set('phone')} />
        <Input
          label="Website"
          hint="Must start with http:// or https://"
          type="url"
          value={form.website}
          onChange={set('website')}
        />
        <Input
          label="Country"
          hint="Two-letter code, e.g. GB."
          maxLength={2}
          value={form.country}
          onChange={set('country')}
        />
        <Button type="submit" loading={busy}>
          Save details
        </Button>
      </form>
    </Card>
  );
}

function SecurityTab() {
  const { toast } = useToast();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [linked, setLinked] = useState<string[] | null>(null);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    auth.sessions().then(setSessions).catch(() => setSessions([]));
    social.linked().then((r) => setLinked(r.providers)).catch(() => setLinked([]));
  }, []);

  useEffect(load, [load]);

  const onChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.changePassword(current, next);
      setCurrent('');
      setNext('');
      toast('Password changed.', 'success');
    } catch (err) {
      setError(err instanceof AuthError ? err.message : 'Could not change your password.');
    } finally {
      setBusy(false);
    }
  };

  const onUnlink = async (provider: string) => {
    try {
      await social.unlink(provider);
      toast(`${provider} disconnected.`, 'success');
      load();
    } catch (err) {
      // The API refuses to remove the last way in (Auth.LastCredential), otherwise disconnecting
      // a provider from an account that has no password locks the customer out permanently.
      toast(err instanceof AuthError ? err.message : 'Could not disconnect.', 'danger');
    }
  };

  const onLink = async (provider: string) => {
    try {
      const { start_url } = await social.linkStart(provider);
      social.followStartUrl(start_url);
    } catch {
      toast('Could not start linking.', 'danger');
    }
  };

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="text-body font-semibold text-text">Password</h2>
        <form onSubmit={onChangePassword} className="mt-4 space-y-4">
          {error && (
            <p className="rounded-md border border-danger bg-danger/5 px-4 py-3 text-body text-text" role="alert">
              {error}
            </p>
          )}
          <Input
            label="Current password"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
          <Input
            label="New password"
            hint="At least 8 characters."
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
          <Button type="submit" loading={busy}>
            Change password
          </Button>
        </form>
      </Card>

      <Card className="p-6">
        <h2 className="text-body font-semibold text-text">Connected accounts</h2>
        {linked === null ? (
          <p className="mt-3 text-body text-muted">Loading…</p>
        ) : linked.length === 0 ? (
          <>
            <p className="mt-3 text-body text-muted">No providers connected.</p>
            <div className="mt-3">
              <Button variant="secondary" onClick={() => void onLink('Google')}>
                Connect Google
              </Button>
            </div>
          </>
        ) : (
          <ul className="mt-3 space-y-3">
            {linked.map((p) => (
              <li key={p} className="flex items-center justify-between gap-3">
                <span className="text-body text-text">{p}</span>
                <Button variant="ghost" onClick={() => void onUnlink(p)}>
                  Disconnect
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-6">
        <h2 className="text-body font-semibold text-text">Where you are signed in</h2>
        <p className="mt-1 text-caption text-muted">
          Signing out a session revokes it everywhere, immediately.
        </p>
        {sessions === null ? (
          <p className="mt-3 text-body text-muted">Loading…</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {sessions.map((s) => (
              <li key={s.family_id} className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-caption text-muted">
                  {s.ip_address || 'unknown address'} · started{' '}
                  {new Date(s.created_at).toLocaleDateString()}
                  {s.is_current && ' · this device'}
                </span>
                <Button
                  variant="ghost"
                  onClick={async () => {
                    await auth.revokeSession(s.family_id);
                    load();
                  }}
                >
                  Sign out
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
