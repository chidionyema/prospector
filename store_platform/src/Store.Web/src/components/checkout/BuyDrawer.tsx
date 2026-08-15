import React from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { buttonClasses, Icon, Modal } from '@/components/ui';
import { BuyerIdentityNote } from '@/components/checkout/BuyerIdentityNote';
import PackBuyButton from '@/components/checkout/PackBuyButton';
import { PACK_DOCUMENTS } from '@/components/marketing/PackContents';
import { usePackCheckout } from '@/lib/checkout/usePackCheckout';
import { formatPrice, Pack } from '@/lib/api/client';
import { formatPriceForMarket, type Currency } from '@/lib/fx';
import { textLinkClass } from '@/components/ui';

// Loaded on demand. `BuyDrawerProvider` mounts on the homepage for EVERY visitor
// (`pages/index.tsx`), so a static import here put the full `@stripe/react-stripe-js` Elements
// wrapper into `/`'s own First Load JS for every shelf browser, not just the ones who buy. See
// the matching note in `pages/pack/[id].tsx`, where the same panel is used the same way.
const EmbeddedCheckoutPanel = dynamic(
  () => import('@/components/checkout/EmbeddedCheckoutPanel').then((m) => m.EmbeddedCheckoutPanel),
  { ssr: false },
);

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
 *   - main characteristics → the nine documents, from the same `PACK_DOCUMENTS` the pack
 *     page and homepage render, so the three surfaces can never promise different things;
 *   - total price → `formatPrice(pack.price)`, the catalogue's own string, never recomputed.
 *     A non-GBP visitor also sees the converted figure, but the GBP line is the one labelled
 *     "Total" and it is never replaced: reg. 13 wants the price the buyer will actually be
 *     bound to, and an FX estimate from a 24-hour-cached table is not that number;
 *   - cancellation right → the 14-day line and a link to /refund;
 *   - and the honesty note that a pack is grounded research, not a promise of success.
 *
 * The buy path itself is `usePackCheckout`, the same hook the pack page runs, not a copy. See
 * that module for the three production incidents its branches encode.
 */
function BuyDrawer({
  pack,
  open,
  onClose,
  currency = 'GBP',
}: {
  pack: Pack;
  open: boolean;
  onClose: () => void;
  currency?: Currency;
}) {
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
          {/* The anchor the visitor has been reading all the way down the shelf, then the exact
              figure they will be bound to. Both, labelled, in one block -- the failure this
              replaces was the two numbers sitting a line apart with neither one explained. */}
          <div className="flex items-baseline justify-between">
            <span className="text-meta font-semibold text-muted">One time price</span>
            <span className="text-h2 font-semibold text-text">
              {currency === 'GBP' ? priceLabel : formatPriceForMarket(pack.price, currency)}
            </span>
          </div>
          {currency !== 'GBP' && (
            <div className="flex items-baseline justify-between text-caption font-medium text-muted">
              <span>Total charged</span>
              <span className="font-mono">{priceLabel} GBP</span>
            </div>
          )}

          {checkoutError && (
            <div className="rounded-md border border-danger/20 bg-danger/5 p-3 text-caption text-danger">
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
                currency={currency}
                className="w-full"
              />
              <BuyerIdentityNote className="text-caption leading-relaxed text-muted" />
            </>
          ) : (
            /* Not buyable yet. The drawer says so rather than showing a dead button, and sends
               the buyer to the full page, which owns the "notify me" path. */
            <Link
              href={`/pack/${pack.id}`}
              className={buttonClasses({ size: 'lg', fullWidth: true })}
            >
              Checkout opens shortly, see the pack
            </Link>
          )}
        </div>
      }
    >
      <div className="space-y-5">
        {pack.oneLine && <p className="text-meta leading-relaxed text-muted">{pack.oneLine}</p>}

        <div>
          <span className="text-caption font-medium text-subtle">What you get</span>
          <ul className="mt-2 space-y-1.5">
            {PACK_DOCUMENTS.map((item) => (
              <li key={item.section} className="flex items-start gap-2 text-meta text-text">
                <Icon name="check" size={14} className="mt-1 flex-none text-success" />
                <span>{item.title}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-2 border-t border-border pt-4">
          {([
            { icon: 'shield', text: '14 day money back, no questions asked' },
            { icon: 'download', text: 'Instant download the moment you pay' },
            { icon: 'lock', text: `Secure checkout via ${providerLabel}` },
          ] as const).map((feat) => (
            <div key={feat.text} className="flex items-center gap-3 text-caption text-muted">
              <Icon name={feat.icon} size={14} className="text-subtle" />
              {feat.text}
            </div>
          ))}
        </div>

        <p className="text-caption leading-relaxed text-muted">
          A pack is evidence-backed research, not a promise of business success. See our{' '}
          <Link href="/refund" className={textLinkClass()}>
            refund policy
          </Link>
          . The full evidence, every check, every cited source, is on the{' '}
          <Link href={`/pack/${pack.id}`} className={textLinkClass()}>
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

export function BuyDrawerProvider({
  children,
  currency = 'GBP',
}: {
  children: React.ReactNode;
  /** The visitor's display currency, from the host page's `getServerSideProps` geo lookup. */
  currency?: Currency;
}) {
  const [pack, setPack] = React.useState<Pack | null>(null);
  return (
    <RequestBuyContext.Provider value={setPack}>
      {children}
      {/* Keyed by id so switching packs remounts the checkout state. Without the key, a session
          opened for one pack would survive into the next drawer, and paying for the wrong pack
          is the one bug this surface must not be able to have. */}
      {pack && (
        <BuyDrawer key={pack.id} pack={pack} open onClose={() => setPack(null)} currency={currency} />
      )}
    </RequestBuyContext.Provider>
  );
}

export function useRequestBuy() {
  return React.useContext(RequestBuyContext);
}
