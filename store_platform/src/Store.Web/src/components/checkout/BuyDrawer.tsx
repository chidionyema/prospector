import React from 'react';
import Link from 'next/link';
import { Icon, Modal } from '@/components/ui';
import { EmbeddedCheckoutPanel } from '@/components/checkout/EmbeddedCheckoutPanel';
import { BuyerIdentityNote } from '@/components/checkout/BuyerIdentityNote';
import PackBuyButton from '@/components/checkout/PackBuyButton';
import { PACK_CONTENTS } from '@/components/marketing/PackContents';
import { usePackCheckout } from '@/lib/checkout/usePackCheckout';
import { formatPrice, Pack } from '@/lib/api/client';

/**
 * Buy one pack without leaving the shelf.
 *
 * The friction this removes is real: a buyer persuaded by the card, which since the card
 * rewrite carries the outcome, the mechanism and a cited proof line, still had to load a new
 * page, scroll to the sticky panel, and buy there. The basket does not solve it either: it is
 * deliberately secondary (`AddToCartButton`), and routing a single purchase through
 * add → open basket → checkout taxes the common case to serve the rarer one.
 *
 * **What this drawer is NOT allowed to be: a shortcut past the evidence.**
 *
 * A £49 purchase made from a card the buyer cannot interrogate would be a worse-informed sale
 * than the pack page offers, on a storefront whose entire position is that it shows its
 * working. It would also drop the pre-contract information a distance sale owes the buyer
 * before they are bound (Consumer Contracts Regulations 2013, reg. 13, main characteristics,
 * total price, and the cancellation right, given before the order is placed).
 *
 * So the drawer carries that set in full, and the whole page stays one click away:
 *
 *   - main characteristics → the eight deliverables, from the same `PACK_CONTENTS` the pack
 *     page and homepage render, so the three surfaces can never promise different things;
 *   - total price → `formatPrice(pack.price)`, the catalogue's own string, never recomputed;
 *   - cancellation right → the 14-day line and a link to /refund;
 *   - and the honesty note that a pack is grounded research, not a promise of success.
 *
 * The buy path itself is `usePackCheckout`, the same hook the pack page runs, not a copy. See
 * that module for the three production incidents its branches encode.
 */
function BuyDrawer({ pack, open, onClose }: { pack: Pack; open: boolean; onClose: () => void }) {
  const {
    checkingOut,
    checkoutError,
    clientSecret,
    canCheckout,
    provider,
    buy,
    handleUnreachable,
    closeOverlay,
  } = usePackCheckout(pack);

  const priceLabel = formatPrice(pack.price);
  const providerLabel = provider === 'stripe' ? 'Stripe' : 'Paddle';
  const name = pack.cardLine || pack.headline || pack.title;

  // Stripe's overlay is a full-viewport panel of its own, so the drawer steps out of the way
  // rather than nesting a payment iframe inside a scrolling side sheet.
  if (clientSecret) {
    return (
      <EmbeddedCheckoutPanel
        clientSecret={clientSecret}
        title={pack.title}
        onClose={() => {
          closeOverlay();
          onClose();
        }}
        onUnreachable={handleUnreachable}
      />
    );
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={name}
      placement="right"
      footer={
        <div className="space-y-3">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-semibold text-muted">One time price</span>
            <span className="text-2xl font-black tracking-tight text-text">{priceLabel}</span>
          </div>

          {checkoutError && (
            <div className="rounded-lg border border-danger/20 bg-danger/5 p-3 text-xs text-danger">
              {checkoutError}
            </div>
          )}

          {canCheckout ? (
            <>
              {/* US-1: the drawer's buy action is the same canonical <PackBuyButton> the shelf
                  and the pack page use. The drawer passes its own `usePackCheckout` flow so
                  the button's click opens the embedded overlay the drawer is already rendering
                  when `clientSecret` lands. */}
              <PackBuyButton
                pack={pack}
                variant="drawer"
                buy={buy}
                checkingOut={checkingOut}
                canCheckout={canCheckout}
                className="w-full"
              />
              <BuyerIdentityNote className="text-xs leading-relaxed text-muted" />
            </>
          ) : (
            /* Not buyable yet. The drawer says so rather than showing a dead button, and sends
               the buyer to the full page, which owns the "notify me" path. */
            <Link
              href={`/pack/${pack.id}`}
              className="block w-full rounded-xl bg-text py-4 text-center text-sm font-bold uppercase tracking-wide text-white"
            >
              Checkout opens shortly, see the pack
            </Link>
          )}
        </div>
      }
    >
      <div className="space-y-5">
        {pack.oneLine && <p className="text-sm leading-relaxed text-muted">{pack.oneLine}</p>}

        <div>
          <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-muted">
            What you get
          </span>
          <ul className="mt-2 space-y-1.5">
            {PACK_CONTENTS.map((item) => (
              <li key={item.filename} className="flex items-start gap-2 text-sm text-text">
                <span aria-hidden className="flex-none">{item.emoji}</span>
                <span>{item.title}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-2 border-t border-border/70 pt-4">
          {([
            { icon: 'shield', text: '14 day money back, no questions asked' },
            { icon: 'download', text: 'Instant download the moment you pay' },
            { icon: 'lock', text: `Secure checkout via ${providerLabel}` },
          ] as const).map((feat) => (
            <div key={feat.text} className="flex items-center gap-3 text-xs font-medium text-muted">
              <Icon name={feat.icon} size={14} className="text-text/60" />
              {feat.text}
            </div>
          ))}
        </div>

        <p className="text-[11px] leading-relaxed text-muted">
          A pack is grounded research, not a promise of business success. See our{' '}
          <Link href="/refund" className="font-semibold text-primary hover:underline">
            refund policy
          </Link>
          . The full evidence, every check, every cited source, is on the{' '}
          <Link href={`/pack/${pack.id}`} className="font-semibold text-primary hover:underline">
            pack page
          </Link>
          .
        </p>
      </div>
    </Modal>
  );
}

/**
 * One drawer for the whole shelf, reached without threading a callback through every card.
 *
 * `null` outside a provider, and that is the useful default rather than a crash: a card rendered
 * somewhere with no drawer mounted simply shows no Buy affordance and keeps its link to the pack
 * page, which is the behaviour every card had before this existed.
 */
const RequestBuyContext = React.createContext<((pack: Pack) => void) | null>(null);

export function BuyDrawerProvider({ children }: { children: React.ReactNode }) {
  const [pack, setPack] = React.useState<Pack | null>(null);
  return (
    <RequestBuyContext.Provider value={setPack}>
      {children}
      {/* Keyed by id so switching packs remounts the checkout state. Without the key, a session
          opened for one pack would survive into the next drawer, and paying for the wrong pack
          is the one bug this surface must not be able to have. */}
      {pack && <BuyDrawer key={pack.id} pack={pack} open onClose={() => setPack(null)} />}
    </RequestBuyContext.Provider>
  );
}

export function useRequestBuy() {
  return React.useContext(RequestBuyContext);
}
