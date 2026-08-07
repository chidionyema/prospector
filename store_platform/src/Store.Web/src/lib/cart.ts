import React from 'react';

/**
 * The basket: several packs, one payment.
 *
 * Every pack is a one-off digital download, so there is no quantity, a pack is in the basket or
 * it is not. That is why this is a set of lines rather than a map of counts, and why adding
 * something already present is a no-op rather than an increment.
 *
 * The stored title and price are a DISPLAY SNAPSHOT taken when the pack was added. They are never
 * what the buyer is charged: `POST /checkout` prices the basket from the catalogue server-side and
 * refuses ids that are no longer listed. A stale snapshot can therefore make the drawer show an
 * old price, but it can never make the wrong amount leave a card.
 */
export interface CartLine {
  id: string;
  title: string;
  /** Display string exactly as the catalogue served it, e.g. "£49.00". */
  price: string;
  /**
   * The same price in pence, carried for ONE reason: `checkout_started` is the numerator of the
   * price→checkout rate and `trackPriceEvent` (lib/analytics.ts:75) emits nothing without it.
   *
   * Optional, and it has to be. Baskets live in localStorage and survive deploys, so lines
   * written before this field existed will never have it, and those lines emit no beacon rather
   * than a guessed one. Not derived from `price` either: that string is a display snapshot the
   * doc above calls stale by design, and pence maps one-to-one onto a pricing RUNG
   * (`config.yaml listing.pricing.rungs`), so a re-parsed stale string would label the event
   * with a rung the catalogue has since moved off.
   */
  pricePence?: number;
}

/** Mirrors StripeProvider.MaxCheckoutLines, the server refuses a longer basket. */
export const MAX_CART_LINES = 10;

const STORAGE_KEY = 'mumchimp.cart.v1';

// --- Pure operations. Tested directly; the store below is a thin shell around them. ---

export function addLine(lines: CartLine[], line: CartLine): CartLine[] {
  if (lines.some((l) => l.id === line.id)) return lines;
  if (lines.length >= MAX_CART_LINES) return lines;
  return [...lines, line];
}

export function removeLine(lines: CartLine[], id: string): CartLine[] {
  return lines.filter((l) => l.id !== id);
}

export function hasLine(lines: CartLine[], id: string): boolean {
  return lines.some((l) => l.id === id);
}

/**
 * Sum the display prices back into one display total.
 *
 * Returns null when any line's price cannot be read as a currency amount, or when the lines do not
 * agree on a symbol, a total that quietly drops or mixes a currency is worse than no total, since
 * the buyer would reconcile it against their card statement and find a different number. The
 * drawer shows the per-line prices and lets Stripe state the total in that case.
 */
export function cartTotal(lines: CartLine[]): string | null {
  if (lines.length === 0) return null;

  let symbol: string | null = null;
  let pence = 0;

  for (const line of lines) {
    const match = /^\s*([^\d\s]+)\s*([\d,]+(?:\.\d{1,2})?)\s*$/.exec(line.price ?? '');
    if (!match) return null;
    if (symbol !== null && symbol !== match[1]) return null;
    symbol = match[1];
    pence += Math.round(parseFloat(match[2].replace(/,/g, '')) * 100);
  }

  return `${symbol}${(pence / 100).toFixed(2)}`;
}

/** Drop anything that is not a well-formed line. Storage is user-writable and survives deploys. */
export function parseStoredCart(raw: string | null): CartLine[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((l): l is CartLine =>
        typeof l === 'object' && l !== null &&
        typeof (l as CartLine).id === 'string' && (l as CartLine).id.length > 0 &&
        typeof (l as CartLine).title === 'string' &&
        typeof (l as CartLine).price === 'string')
      // `pricePence` is optional, so its ABSENCE must not drop a line (that would empty every
      // basket written before the field existed). A present-but-junk value is stripped instead:
      // storage is user-writable, and an analytics beacon is the one consumer.
      .map((l) => (typeof l.pricePence === 'number' && Number.isFinite(l.pricePence)
        ? l
        : { id: l.id, title: l.title, price: l.price }))
      .slice(0, MAX_CART_LINES);
  } catch {
    return [];
  }
}

// --- The store. One module-level snapshot shared by every subscriber. ---

let snapshot: CartLine[] = [];
let hydrated = false;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function persist(lines: CartLine[]) {
  snapshot = lines;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(lines));
  } catch {
    // Private browsing, a full quota, or storage disabled entirely. The basket still works for
    // this page view; it just will not survive a reload. Losing it is not worth an error screen.
  }
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);

  // Hydrate on the first subscription rather than at module scope: this module is imported during
  // SSR, where localStorage does not exist.
  if (!hydrated) {
    hydrated = true;
    snapshot = parseStoredCart(window.localStorage.getItem(STORAGE_KEY));
  }

  // A second tab is the same basket. Without this, checking out in one tab leaves the other
  // showing packs the buyer has already paid for.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) return;
    snapshot = parseStoredCart(event.newValue);
    emit();
  };
  window.addEventListener('storage', onStorage);

  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

/** The server snapshot is a stable empty basket: the server cannot know what is in localStorage,
 *  and returning a fresh [] each call would loop useSyncExternalStore. */
const SERVER_SNAPSHOT: CartLine[] = [];

export interface Cart {
  lines: CartLine[];
  count: number;
  total: string | null;
  add: (line: CartLine) => void;
  remove: (id: string) => void;
  clear: () => void;
  has: (id: string) => boolean;
  /** False until the browser has read localStorage, so the header can avoid rendering a "0" that
   *  flips to "3" a frame later. */
  ready: boolean;
}

export function useCart(): Cart {
  const lines = React.useSyncExternalStore(subscribe, () => snapshot, () => SERVER_SNAPSHOT);
  const ready = React.useSyncExternalStore(subscribe, () => hydrated, () => false);

  return React.useMemo<Cart>(() => ({
    lines,
    count: lines.length,
    total: cartTotal(lines),
    add: (line) => persist(addLine(snapshot, line)),
    remove: (id) => persist(removeLine(snapshot, id)),
    clear: () => persist([]),
    has: (id) => hasLine(lines, id),
    ready,
  }), [lines, ready]);
}
