/**
 * The shapes the shop reads return.
 *
 * They live here rather than in each page because the order row appears in two screens — the list
 * and the detail — and a second copy of the type is how one of them quietly stops rendering a
 * field the engine started sending.
 *
 * Every field is nullable on purpose. The store fills these from a database that has rows written
 * by three different code paths; a type that promises a string is a type that renders `undefined`
 * the first time one of them writes nothing.
 */

export type Entitlement = {
  status: string | null;
  downloadCount: number | null;
  lastDownloadedAtUtc: string | null;
  expiresAtUtc: string | null;
};

export type DeliverySummary = {
  /** The delivery ROW id — what `deliveries.resend` takes. Not the order id. */
  id?: string | number | null;
  /** The order this delivery belongs to. A different number from `id`. */
  orderId?: string | number | null;
  sentAtUtc: string | null;
  attempts: number | null;
  lastError: string | null;
  state: string | null;
};

export type Order = {
  id: string;
  createdAtUtc: string | null;
  buyerEmail: string | null;
  packId: string | null;
  packTitle: string | null;
  amountMinorUnits: number | null;
  currency: string | null;
  country: string | null;
  status: string | null;
  providerTransactionId: string | null;
  entitlement: Entitlement | null;
  delivery: DeliverySummary | null;
};

/**
 * The delivery states, worst first.
 *
 * `abandoned` is the one that needs saying out loud. It means the drain hit `Delivery:MaxAttempts`
 * and STOPPED. A failed delivery is still being retried; an abandoned one is a buyer who paid,
 * holds an entitlement, and will never be sent their link by any automatic process. Nothing will
 * move it without a person pressing resend. So it outranks `failed` everywhere: in the sort, in
 * the headline, and in the words on the row.
 */
export const DELIVERY_STATES = ['all', 'unsent', 'pending', 'failed', 'abandoned', 'sent'] as const;

/** Higher is worse. This is the ordering, not a colour — colours only have four steps. */
export function deliverySeverity(state: string | null | undefined): number {
  const s = (state ?? '').toLowerCase();
  if (s === 'abandoned') return 4;
  if (s === 'failed' || s === 'bounced') return 3;
  if (s === 'pending' || s === 'queued' || s === 'retrying') return 2;
  if (s === 'sent' || s === 'delivered') return 0;
  return 1; // unknown: worth a look, not worth panic
}

/** How a delivery state is coloured. Anything unknown stays neutral rather than guessing. */
export function deliveryTone(state: string | null | undefined): 'ok' | 'warn' | 'bad' | 'mute' {
  const s = (state ?? '').toLowerCase();
  if (s === 'sent' || s === 'delivered') return 'ok';
  if (s === 'abandoned' || s === 'failed' || s === 'bounced') return 'bad';
  if (s === 'pending' || s === 'queued' || s === 'retrying' || s === 'unsent') return 'warn';
  return 'mute';
}

/** Whether anything automatic will try this delivery again. Abandoned is the only hard no. */
export function isAbandoned(state: string | null | undefined): boolean {
  return (state ?? '').toLowerCase() === 'abandoned';
}

/** How an order status is coloured. */
export function orderTone(status: string | null | undefined): 'ok' | 'warn' | 'bad' | 'mute' {
  const s = (status ?? '').toLowerCase();
  if (s === 'paid' || s === 'complete' || s === 'completed' || s === 'fulfilled') return 'ok';
  if (s === 'refunded' || s === 'disputed' || s === 'failed' || s === 'cancelled') return 'bad';
  if (s === 'pending' || s === 'open' || s === 'processing') return 'warn';
  return 'mute';
}

/** Plain words for a delivery state, so nobody has to know the store's vocabulary. */
export function deliveryWords(state: string | null | undefined): string {
  const s = (state ?? '').toLowerCase();
  if (s === 'sent' || s === 'delivered') return 'the link was sent';
  if (s === 'abandoned') {
    return 'the drain tried the most times it is allowed to and gave up. Nothing will try again on its own.';
  }
  if (s === 'failed' || s === 'bounced') return 'sending the link failed, and it is still being retried';
  if (s === 'pending' || s === 'queued' || s === 'unsent') return 'the link has not been sent yet';
  if (s === 'retrying') return 'sending the link is being retried';
  if (!s) return 'no delivery was recorded for this order';
  return s;
}

/** What the resend actually did. The two outcomes are not the same event. */
/**
 * What a resend actually did, in plain words.
 *
 * There is only ONE outcome, `requeued`. There used to be a second one, `duplicated`, and the
 * database refuted it: `PendingDeliveries.EntitlementId` is UNIQUE, which is what makes a duplicate
 * webhook idempotent, so a second row for the same entitlement cannot exist.
 *
 * The distinction that matters is `previousSentAt`. When the row had already been sent, requeuing
 * it CLEARS that timestamp — clearing it is the only legal way to put the row back in the queue —
 * so the record that the first email went out is destroyed and the buyer gets a second email. That
 * is a different event from requeuing something that never went out, and it is said differently.
 */
export function resendWords(
  action: string | null | undefined,
  previousSentAt?: string | null,
): string {
  const a = (action ?? '').toLowerCase();
  if (a !== 'requeued') {
    return 'The store did not say what it did. Read the receipt below before assuming anything was queued.';
  }
  if (previousSentAt) {
    return `Requeued — and this link had ALREADY been sent, at ${previousSentAt}. That send time has been cleared, because clearing it is the only way to put the row back in the queue, so the record of the first email is gone. The buyer will receive a second email when the drain next runs.`;
  }
  return 'Requeued. This link had never been sent, so its attempt count is back to zero and the delivery drain will pick it up on its next pass. This button sent nothing itself.';
}
