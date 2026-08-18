import React from 'react';
import Link from 'next/link';
import { Button, Icon, Modal, cx, useToast } from '@/components/ui';
import { createCartCheckout, formatPrice, PacksUnavailableError } from '@/lib/api/client';
import { useCart } from '@/lib/cart';
import { track, trackPriceEvent } from '@/lib/analytics';
import { useAuth } from '@/lib/auth/AuthContext';
import { BuyerIdentityNote } from '@/components/checkout/BuyerIdentityNote';

/**
 * The basket, in the header.
 *
 * Hidden entirely while empty. A permanent "0 items" is a standing invitation to a step the buyer
 * has not opted into, and the shelf's own Buy-now path never needs it.
 */
export function CartButton() {
  const cart = useCart();
  // Above the early return below, because hooks cannot be conditional. Null for a guest, which is
  // the answer the basket wants: checkout carries an address only when one is already proven.
  const { account } = useAuth();
  const { toast } = useToast();
  const [open, setOpen] = React.useState(false);
  const [checkingOut, setCheckingOut] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [justAdded, setJustAdded] = React.useState(false);
  const prevCount = React.useRef(cart.count);

  React.useEffect(() => {
    if (cart.count > prevCount.current) {
      setJustAdded(true);
      const timer = setTimeout(() => setJustAdded(false), 600);
      prevCount.current = cart.count;
      return () => clearTimeout(timer);
    }
    prevCount.current = cart.count;
  }, [cart.count]);

  if (!cart.ready || cart.count === 0) return null;

  const checkout = async () => {
    setCheckingOut(true);
    setError(null);

    // The basket is the SECOND checkout path, and until now the only untracked one. Measured
    // 2026-08-07 over a 90-day production window: price_viewed 172, checkout_completed 1,
    // checkout_started ZERO, a funnel with one completion and no starts, because
    // `usePackCheckout.buy()` (which does emit, at usePackCheckout.ts:98) is not on this path.
    // One event per line, matching price_viewed's per-pack granularity so the two compose into
    // a rate. Fired on INTENT, before the provider call and outside the try, for the same
    // reason the single-pack path gives: a numerator that counted only checkouts Stripe managed
    // to open would hide exactly the case a price change is most likely to cause.
    cart.lines.forEach((line) => trackPriceEvent('checkout_started', line));

    try {
      // createCartCheckout already refuses any URL that is not Stripe's hosted checkout.
      window.location.href = await createCartCheckout(
        cart.lines.map((l) => l.id),
        account?.email ?? null,
      );
    } catch (err) {
      if (err instanceof PacksUnavailableError) {
        // The catalogue moved under a basket that had been sitting in localStorage. Prune exactly
        // what the API named and say so, rather than failing with nothing the buyer can act on.
        const dropped = cart.lines.filter((l) => err.packIds.includes(l.id)).map((l) => l.title);
        err.packIds.forEach((id) => cart.remove(id));
        setError(
          `${dropped.length === 1 ? 'One pack is' : `${dropped.length} packs are`} no longer available` +
          `${dropped.length > 0 ? ` (${dropped.join(', ')})` : ''} and has been removed. ` +
          'Everything else is still ready to buy.',
        );
      } else {
        setError(err instanceof Error && err.message ? err.message : 'Checkout failed. Please try again.');
      }
      setCheckingOut(false);
      return;
    }
    // Deliberately no setCheckingOut(false) on success: the browser is navigating to Stripe, and
    // re-enabling the button in the meantime invites a second click and a second session.
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Basket, ${cart.count} ${cart.count === 1 ? 'pack' : 'packs'}`}
        className="relative inline-flex items-center gap-2 rounded-md px-3 py-2 text-meta font-semibold text-text transition-colors hover:bg-bg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        <Icon name="cart" size={18} />
        <span className="hidden sm:inline">Basket</span>
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-sm bg-primary px-1.5 text-caption font-medium text-on-primary">
          {justAdded ? <span className="animate-rise" data-just-added>{cart.count}</span> : cart.count}
        </span>
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Your basket"
        placement="right"
        footer={
          <div className="space-y-3">
            <div className="flex items-baseline justify-between">
              <span className="text-meta font-semibold text-muted">
                {cart.count} {cart.count === 1 ? 'pack' : 'packs'}
              </span>
              {cart.total && <span className="text-h2 font-semibold text-text">{formatPrice(cart.total)}</span>}
            </div>
            <Button variant="primary" fullWidth loading={checkingOut} onClick={checkout}>
              Pay once for {cart.count === 1 ? 'this pack' : 'all of these'}
            </Button>
            {/* Trust badges */}
            <div className="flex items-center justify-center gap-4 text-caption text-muted">
              <span className="inline-flex items-center gap-1">
                <Icon name="lock" size={11} /> Secure checkout
              </span>
              <span className="inline-flex items-center gap-1">
                <Icon name="download" size={11} /> Instant download
              </span>
              <span className="inline-flex items-center gap-1">
                <Icon name="shield" size={11} /> 14 day refund
              </span>
            </div>
            <BuyerIdentityNote className="text-center text-caption leading-relaxed text-muted" />
          </div>
        }
      >
        {error && (
          <p role="alert" className="mb-4 rounded-md border border-warning bg-warning/5 p-3 text-meta text-text">
            {error}
          </p>
        )}

        <ul className="divide-y divide-border">
          {cart.lines.map((line) => (
            <li key={line.id} className="flex items-start gap-3 py-4">
              <div className="min-w-0 flex-1">
                <Link
                  href={`/pack/${line.id}`}
                  onClick={() => setOpen(false)}
                  className="text-meta font-semibold leading-snug text-text hover:text-primary"
                >
                  {line.title}
                </Link>
                <p className="mt-1 lede">{formatPrice(line.price)}</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  track('basket_removed', line.id);
                  cart.remove(line.id);
                  toast(`Removed "${line.title}" from basket`, 'info');
                }}
                aria-label={`Remove ${line.title} from basket`}
                className={cx(
                  'inline-flex h-11 w-11 flex-none items-center justify-center rounded-md text-muted transition-colors sm:h-8 sm:w-8',
                  'hover:bg-danger/10 hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
                )}
              >
                <Icon name="trash" size={15} />
              </button>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}
