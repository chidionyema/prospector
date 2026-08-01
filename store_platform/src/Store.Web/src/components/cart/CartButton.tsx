import React from 'react';
import Link from 'next/link';
import { Button, Icon, Modal, cx } from '@/components/ui';
import { createCartCheckout, formatPrice, PacksUnavailableError } from '@/lib/api/client';
import { useCart } from '@/lib/cart';
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
  const [open, setOpen] = React.useState(false);
  const [checkingOut, setCheckingOut] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  if (!cart.ready || cart.count === 0) return null;

  const checkout = async () => {
    setCheckingOut(true);
    setError(null);
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
        className="relative inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-text transition-colors hover:bg-bg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
      >
        <Icon name="cart" size={18} />
        <span className="hidden sm:inline">Basket</span>
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-bold text-white">
          {cart.count}
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
              <span className="text-sm font-semibold text-muted">
                {cart.count} {cart.count === 1 ? 'pack' : 'packs'}
              </span>
              {/* Absent when the lines do not agree on a currency or a price will not parse —
                  Stripe states the authoritative total on the next screen either way. */}
              {cart.total && <span className="text-2xl font-black tracking-tight text-text">{formatPrice(cart.total)}</span>}
            </div>
            <Button variant="primary" fullWidth loading={checkingOut} onClick={checkout}>
              Pay once for {cart.count === 1 ? 'this pack' : 'all of these'}
            </Button>
            <p className="text-center text-xs text-muted">
              One card entry, one charge, instant download of every pack.
            </p>
            <BuyerIdentityNote className="text-center text-xs leading-relaxed text-muted" />
          </div>
        }
      >
        {error && (
          <p role="alert" className="mb-4 rounded-lg border border-warning bg-warning/5 p-3 text-sm text-text">
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
                  className="text-sm font-bold leading-snug text-text hover:text-primary"
                >
                  {line.title}
                </Link>
                <p className="mt-1 text-sm font-semibold text-muted">{formatPrice(line.price)}</p>
              </div>
              <button
                type="button"
                onClick={() => cart.remove(line.id)}
                aria-label={`Remove ${line.title} from basket`}
                className={cx(
                  'inline-flex h-8 w-8 flex-none items-center justify-center rounded-lg text-muted transition-colors',
                  'hover:bg-danger/10 hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
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
