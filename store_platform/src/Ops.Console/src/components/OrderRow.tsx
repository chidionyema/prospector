/**
 * One order, as a card that links to itself.
 *
 * A card and not a table row. The founder reads this on a 390px phone inside Telegram, and the
 * nine facts an order carries need 900px as columns. Every long token here — the buyer's email,
 * the `pi_…` transaction id, an error string — is wrapped, because one unbroken 60-character
 * string is all it takes to push the whole page off the side.
 *
 * It lives in components/ rather than inside the Orders screen because the Disputes screen shows
 * the same rows. A second copy would be the thing that quietly stops rendering `abandoned` on one
 * of the two screens.
 */
import Link from 'next/link';

import { Pill } from '@/components/ui';
import { money } from '@/lib/money';
import type { Order } from '@/lib/shop';
import { deliveryTone, isAbandoned, orderTone } from '@/lib/shop';
import { ABSENT, ago, clock } from '@/lib/time';

/**
 * `dateWord` names what the timestamp on the card MEANS. It defaults to "sold" because that is what
 * `createdAtUtc` is on every screen. Disputes passes it explicitly and does not change it: on that
 * screen the reversal has no timestamp at all, so a bare "3 days ago" would read as the age of the
 * dispute, which is a number nothing in the database holds.
 */
export default function OrderRow({ order, dateWord = 'sold' }: { order: Order; dateWord?: string }) {
  const o = order;
  return (
    <Link
      href={`/orders/${encodeURIComponent(o.id)}`}
      className="block rounded-md border border-border bg-surface2 px-4 py-3 hover:bg-surface3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="min-w-0 text-[15px] font-[520]">{o.packTitle || 'untitled pack'}</span>
        <span className="font-mono text-[15px]">{money(o.amountMinorUnits, o.currency)}</span>
      </div>
      <div className="wrap-any mt-1 text-[13px] text-muted">{o.buyerEmail || ABSENT}</div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Pill tone={orderTone(o.status)}>{o.status || 'no status'}</Pill>
        <Pill tone={deliveryTone(o.delivery?.state)}>
          {isAbandoned(o.delivery?.state)
            ? 'abandoned · no retry'
            : o.delivery?.state || 'no delivery row'}
        </Pill>
        {o.entitlement ? (
          <Pill tone="mute">
            {o.entitlement.downloadCount === null
              ? 'downloads not recorded'
              : `${o.entitlement.downloadCount} downloads`}
          </Pill>
        ) : (
          <Pill tone="warn">no entitlement</Pill>
        )}
        {o.country ? <Pill tone="mute">{o.country}</Pill> : null}
      </div>
      <div className="mt-2 text-[12px] text-subtle">
        {o.createdAtUtc ? `${dateWord} ${clock(o.createdAtUtc)} · ${ago(o.createdAtUtc)}` : ABSENT}
      </div>
      <div className="wrap-any mt-1 font-mono text-[11px] text-subtle">{o.id}</div>
      {o.delivery?.lastError ? (
        <div className="wrap-any mt-1 text-[12px] text-bad-strong">{o.delivery.lastError}</div>
      ) : null}
    </Link>
  );
}
