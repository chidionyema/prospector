import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Button, buttonClasses, Card, EmptyState, Input, Money, SegmentedControl, Skeleton, textLinkClass, useToast } from '@/components/ui';
import PackMark from '@/components/ui/PackMark';
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
 * Every date on this surface, in the site's locale.
 *
 * WHAT WAS HERE. `new Date(x).toLocaleDateString()` in three places (the library card, the receipt
 * row, the session row) with NO locale argument. On the founder's 2026-08-15 review that rendered
 * `8/11/2026` on a storefront that prices in £: a date a British buyer reads as 8 November and an
 * American reads as 11 August, on the one page whose whole job is proving what was bought and
 * when. Every other date and number on this site already passes `'en-GB'` explicitly (25 call
 * sites; `pages/kill-log.tsx:175` is this exact shape) -- these three were the only ones that did
 * not, so this is the file rejoining a convention rather than inventing one.
 *
 * The bare call was also a hydration hazard: with no locale the format is the RUNTIME's, so the
 * server's and the browser's need not agree, and React reconciles a text-node mismatch silently.
 *
 * `timeZone: 'UTC'` because `created_at` is an instant, not a calendar day. Without it a 00:30 UTC
 * purchase renders as the PREVIOUS day for a buyer in Los Angeles, and the card then disagrees
 * with the receipt for the same order.
 *
 * Month as `short` rather than numeric removes the ambiguity at the source, instead of relying on
 * the reader knowing which convention the site picked.
 */
function accountDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
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
        // The empty state used to end the conversation. This is a signed-in customer with a
        // confirmed address and nothing bought, which is the single most qualified audience the
        // shop ever has in front of it, and it was shown a paragraph about email addresses and no
        // way forward. The explanation stays, because it is the answer to "where are my orders";
        // the shelf is now also one click away.
        action={
          <Link href="/" className={buttonClasses({ variant: 'secondary' })}>
            Browse the packs
          </Link>
        }
      />
    );
  }

  /*
    THE LIBRARY SHELF.

    WHAT WAS HERE. One card per ORDER, with the packs inside it as rows of plain text. That is the
    merchant's model of the data, not the customer's: nobody comes to this page thinking about
    orders, they come thinking about a specific pack they bought and want to open again. With the
    packs rendered as undifferentiated lines inside grey receipt cards, finding one meant reading.

    WHAT IT IS NOW. The packs come first, as a shelf, each carrying the same generative mark the
    catalogue and pack page draw for it -- deterministically hashed from the pack id, so the mark
    on the shelf is pixel-identical to the one the customer saw when they bought it, and the item
    is recognisable before its title has been read. That is what a library gives you and a receipt
    list does not.

    NOTHING WAS REMOVED. Order date, order status, amount and currency are all still rendered, in
    the ledger below the shelf. They were the only facts the old layout carried, and they belong to
    the order rather than to the pack; putting them in their own block is what allowed the pack to
    stop being a line item.
  */
  const purchases = orders.flatMap((order) =>
    order.items.map((item) => ({ order, item })),
  );

  return (
    <div className="space-y-10">
      <section>
        {/* A HEADING, not a caption. Both section labels were `font-mono text-caption text-subtle`
            lowercase -- "your library · 4 packs" and "receipts" -- which is this kit's DEBUG-label
            idiom, the same styling the store uses for ids and timestamps. They are the only
            structure the page has, and they were set quieter than the rows they govern, so the
            page read as one undifferentiated column of grey. The count keeps the mono, because a
            count IS a checkable quantity (tokens.css: "monospace means you can verify this"). */}
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          {/* "Packs you own" (`mockups/account.html`): plain words for the thing itself. */}
          <h2 className="sec">Packs you own</h2>
          <p className="mono">
            {purchases.length} pack{purchases.length === 1 ? '' : 's'}
          </p>
        </div>
        <p className="lede mt-2">Yours to keep. Download as many times as you like, no expiry.</p>
        <ul className="mt-4 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
          {purchases.map(({ order, item }) => {
            const href = downloadHref(item.download_path);
            return (
              // Keyed on order AND pack: the same pack bought twice (a gift, a re-purchase after a
              // refund) is two rows, and `pack_id` alone would collide and drop one.
              <li
                key={`${order.id}-${item.pack_id}`}
                // `rounded-card`: an owned pack drawn as a bordered row on the surface is a
                // card, and 12px is the card corner the rest of the site uses.
                className="flex overflow-hidden rounded-card border border-border bg-surface"
              >
                {/*
                  THE MARK IS A SPINE NOW, AND THE AXIS IS THE WHOLE FIX.

                  This is the ONLY `<PackMark>` call site left in the app (verified by search,
                  2026-08-15), and it was calling it in exactly the configuration the component's
                  own doc comment forbids. `PackMark.tsx` states the rule -- "bands run
                  PERPENDICULAR TO THE BOX'S LONG AXIS" -- and names this failure: stretched along
                  a WIDE box the bands "become flat lines of RAGGED WIDTH with varying left insets
                  ... precisely, the geometry of a text-line loading placeholder". The box here was
                  `h-16 w-full`, measured 353x64 at 1280 (a 5.5:1 wide box) with the default
                  `axis="across"`, and no `emphasis`, so the bands drew at 0.10-0.34 opacity in
                  inherited grey on `bg-surface2`. That is `components/ui/Skeleton.tsx` -- pale
                  rounded bars of ragged width -- rendered four times over. The founder's word for
                  the page was "a complete shambles"; a library of unloaded skeletons is what he
                  was looking at.

                  A ~48px-wide, full-height spine is the orientation the geometry was drawn for
                  (PackMark's comment cites the row card's 32x48 spine as the one call site where
                  `across` was correct), so the default axis becomes right rather than being
                  overridden, and `emphasis` lifts it to 0.26-0.88 so it reads as a drawn graphic.

                  COLOUR. `currentColor` means the mark takes its ink from this wrapper. The
                  catalogue gives it the twelve-hue SECTOR ink, and `OrderItem` (lib/api/auth.ts:
                  114-121) carries no category, so that ink is not available here without a second
                  fetch per row. Teal is the identity colour and is honest about what it encodes:
                  the FORM still means this pack, and no hue claims a sector we were not told.

                  `morph` stays false (the default) and that is worth not disturbing: a customer
                  who bought the same pack twice would have two elements claiming one
                  `view-transition-name`, and a duplicate name silently disables every view
                  transition on the document rather than just this one.
                */}
                <div
                  aria-hidden
                  className="w-12 shrink-0 self-stretch bg-brand-mark/10 text-brand-mark"
                >
                  {/* `bleed` because the spine fixed the aspect ratio and left the ragged edge:
                      bands of different lengths on a shared baseline read as a bar chart, on the
                      one surface with nothing to measure. See PackMark's `bleed` docblock. */}
                  <PackMark id={item.pack_id} emphasis bleed />
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-3 p-4">
                  <div className="min-w-0">
                    <p className="text-meta font-semibold leading-snug text-text">
                      {item.pack_title}
                    </p>
                    {/* The order number is on the card because it is the JOIN. Price lives in the
                        receipt below and cannot be split per pack (order 2988 is £128.00 for two
                        packs, and the API sends no line amount), so putting a figure here would
                        mean inventing one on the money surface. Printing the reference instead
                        makes the cross-reference exact rather than making the reader match on a
                        date. */}
                    <p className="mt-1 font-mono text-caption text-subtle">
                      {accountDate(order.created_at)} · order {order.id}
                    </p>
                  </div>
                  <div className="mt-auto">
                    {href ? (
                      // A plain anchor, not a fetch: /download/{token} answers with a 302 to a
                      // short-lived presigned URL, and the browser must follow it as a navigation.
                      //
                      // It is a BUTTON now, not `textLinkClass`. Measured at 390px on 2026-08-15:
                      // three "Download" targets 20px tall, against the 44px floor this codebase
                      // enforces explicitly on `Button` (`md: h-11 ... sm:h-10`), on `chipClasses`
                      // and on both footer link columns. The single action the whole page exists
                      // for was the smallest target on it, and set as quiet inline prose.
                      <a href={href} className={buttonClasses({ variant: 'primary' })}>
                        Download
                      </a>
                    ) : item.status === 'revoked' ? (
                      // A bare lowercase "refunded" in the slot where the button goes is a dead
                      // end: it names a state without saying what happened to the money or what
                      // the buyer may do next, and it looks like a failed render.
                      <p className="text-caption text-muted">
                        <span>Refunded.</span> The download was
                        withdrawn when the payment went back. The receipt below is the record.
                      </p>
                    ) : (
                      <p className="text-caption text-muted">
                        <span>Download unavailable.</span> Email{' '}
                        <a href="mailto:support@mumchimp.com" className={textLinkClass()}>
                          support@mumchimp.com
                        </a>{' '}
                        quoting order {order.id} and we will re-issue it.
                      </p>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="sub">Receipts</h2>
          <p className="mono">
            {orders.length} order{orders.length === 1 ? '' : 's'}
          </p>
        </div>
        {/* The two blocks are the same purchases counted two ways, and nothing said so: the shelf
            showed 4 packs, the ledger showed 3 rows, and a reader is left to work out whether one
            went missing. One sentence is cheaper than the support mail. */}
        <p className="mt-1 max-w-prose text-caption text-muted">
          One row per payment, so an order that carried two packs is one row here and two on the
          packs above. The order number is the join.
        </p>
        <ul className="mt-4 list-none p-0">
          {orders.map((order) => (
            <li
              key={order.id}
              className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border/60 py-3 last:border-b-0"
            >
              <span className="font-mono text-caption text-muted">
                order {order.id} · {accountDate(order.created_at)} · {order.status} ·{' '}
                {order.items.length} pack{order.items.length === 1 ? '' : 's'}
              </span>
              {/* `ml-auto` because the row WRAPS at 390px: `justify-between` only right-aligns the
                  amount while both children share a line, so on a narrow screen the money column
                  alternated between the right edge and the left, which reads as a broken table
                  rather than a ledger. */}
              <Money
                cents={order.amount_pence}
                currency={order.currency}
                className="ml-auto"
              />
            </li>
          ))}
        </ul>
      </section>
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
        <h2 className="sub">Password</h2>
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
        <h2 className="sub">Connected accounts</h2>
        {linked === null ? (
          <p className="mt-3 lede">Loading…</p>
        ) : linked.length === 0 ? (
          <>
            <p className="mt-3 lede">No providers connected.</p>
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
        <h2 className="sub">Where you are signed in</h2>
        <p className="mt-1 text-caption text-muted">
          Signing out a session revokes it everywhere, immediately.
        </p>
        {sessions === null ? (
          <p className="mt-3 lede">Loading…</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {sessions.map((s) => (
              <li key={s.family_id} className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-caption text-muted">
                  {s.ip_address || 'unknown address'} · started{' '}
                  {accountDate(s.created_at)}
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
