/**
 * One sale in full: what was bought, what the buyer is entitled to, and every attempt to hand it
 * over.
 *
 * The question this screen exists to answer is "they say they paid and got nothing — what
 * happened". So the delivery attempts are the body of the page, not a footnote, and each one shows
 * its error text in full rather than a status word.
 *
 * SIBLING ORDERS matter and are easy to miss. One payment can create several orders, and a buyer
 * chasing a missing link may be chasing the one that failed out of three that worked. They are
 * listed with their own amounts, each in its own currency, never summed.
 */
import Link from 'next/link';
import { useRouter } from 'next/router';

import ResendDelivery from '@/components/ResendDelivery';
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Mono, Note, Pill, Problem, Row, Spinner } from '@/components/ui';
import { money } from '@/lib/money';
import type { Order } from '@/lib/shop';
import { deliveryTone, deliveryWords, isAbandoned, orderTone } from '@/lib/shop';
import { ABSENT, ago, clock } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type EntitlementRow = {
  id: string;
  packId: string | null;
  status: string | null;
  downloadCount: number | null;
  lastDownloadedAtUtc: string | null;
  expiresAtUtc: string | null;
  contentVersion: string | null;
};

type DeliveryAttempt = {
  /** The delivery ROW id. `deliveries.resend` takes this, never the order id. */
  id: string | number;
  orderId?: string | number | null;
  createdAtUtc: string | null;
  sentAtUtc: string | null;
  attempts: number | null;
  lastError: string | null;
  state: string | null;
};

/**
 * One line the payment provider recorded for this sale.
 *
 * `amountMinorUnits` is the authoritative total for the transaction. It is NOT the same number as
 * the per-pack `splitMinorUnits` on the Revenue screen, and the two must never be added together.
 */
type AuditLine = {
  id: string | number;
  providerProductId: string | null;
  amountMinorUnits: number | null;
  currency: string | null;
  country: string | null;
  occurredAtUtc: string | null;
};

type Sibling = {
  id: string;
  packId: string | null;
  amountPence: number | null;
  currency: string | null;
};

type OrderView = {
  order: Order | null;
  entitlements: EntitlementRow[];
  deliveries: DeliveryAttempt[];
  siblings: Sibling[];
  salesAudit: AuditLine[];
  warnings: string[];
};

export default function OrderDetail() {
  const router = useRouter();
  const id = typeof router.query.id === 'string' ? router.query.id : '';
  const { data, envelope, error, refresh } = useOps<OrderView>(id ? 'order' : null, {
    order_id: id,
  });

  const order = data?.order ?? null;
  const deliveries = data?.deliveries ?? [];
  const entitlements = data?.entitlements ?? [];
  const siblings = data?.siblings ?? [];
  const audit = data?.salesAudit ?? [];
  const undelivered = deliveries.length > 0 && !deliveries.some((d) => d.sentAtUtc);
  // Worse than undelivered: nothing automatic will try again.
  const givenUp = deliveries.some((d) => isAbandoned(d.state));

  return (
    <Shell title="Order" intro={id}>
      {error ? <Problem>{error}</Problem> : null}
      {(data?.warnings ?? []).map((w) => (
        <Problem key={w}>{w}</Problem>
      ))}

      {!data && id ? (
        <Card>
          <Spinner what="this order" />
        </Card>
      ) : null}

      {data && !order ? (
        <Card title="No such order" tone="bad">
          <p className="text-[13px] text-muted">
            The store has no order with this id. The read succeeded, so this is a real answer.
          </p>
        </Card>
      ) : null}

      {order ? (
        <Card
          title={order.packTitle || 'untitled pack'}
          tone={orderTone(order.status) === 'ok' && !undelivered ? 'ok' : 'warn'}
          right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-mono text-[28px]">
              {money(order.amountMinorUnits, order.currency)}
            </span>
            <button onClick={refresh} className="tap text-[13px] text-muted underline">
              re-read
            </button>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Pill tone={orderTone(order.status)}>{order.status || 'no status'}</Pill>
            <Pill tone={deliveryTone(order.delivery?.state)}>
              {order.delivery?.state || 'no delivery row'}
            </Pill>
            {order.country ? <Pill tone="mute">{order.country}</Pill> : null}
          </div>
          <p className="wrap-any mt-3 text-[13px] text-muted">
            {deliveryWords(order.delivery?.state)}
          </p>
          <div className="mt-2">
            <Row label="Buyer">
              <span className="wrap-any">{order.buyerEmail || ABSENT}</span>
            </Row>
            <Row label="Paid at">
              {order.createdAtUtc
                ? `${clock(order.createdAtUtc)} · ${ago(order.createdAtUtc)}`
                : ABSENT}
            </Row>
            <Row label="Pack">
              {order.packId ? (
                <Link className="wrap-any underline" href={`/catalogue/${encodeURIComponent(order.packId)}`}>
                  {order.packId}
                </Link>
              ) : (
                ABSENT
              )}
            </Row>
            <Row label="Payment id">
              <span className="wrap-any">{order.providerTransactionId || ABSENT}</span>
            </Row>
            <Row label="Order id">
              <span className="wrap-any">{order.id}</span>
            </Row>
          </div>
        </Card>
      ) : null}

      {data ? (
        <Card
          title="What the buyer may download"
          tone={entitlements.length === 0 ? 'warn' : 'plain'}
        >
          {entitlements.length === 0 ? (
            <Empty>
              No entitlement is recorded against this order. A paid order with no entitlement is a
              buyer who cannot download anything.
            </Empty>
          ) : null}
          {entitlements.map((e) => (
            <div key={e.id} className="border-t border-border pt-2 first:border-0 first:pt-0">
              <div className="flex flex-wrap items-baseline gap-2">
                <Pill tone={e.status === 'active' ? 'ok' : 'mute'}>{e.status || 'no status'}</Pill>
                <span className="wrap-any font-mono text-[12px] text-subtle">
                  {e.packId || 'no pack id'}
                </span>
              </div>
              <Row label="Downloads">
                {e.downloadCount === null || e.downloadCount === undefined
                  ? 'not recorded'
                  : e.downloadCount}
              </Row>
              <Row label="Last downloaded">
                {e.lastDownloadedAtUtc
                  ? `${clock(e.lastDownloadedAtUtc)} · ${ago(e.lastDownloadedAtUtc)}`
                  : 'never'}
              </Row>
              <Row label="Expires">{e.expiresAtUtc ? clock(e.expiresAtUtc) : 'no expiry'}</Row>
              <Row label="Content version">
                <span className="wrap-any">{e.contentVersion || ABSENT}</span>
              </Row>
            </div>
          ))}
        </Card>
      ) : null}

      {data ? (
        <Card
          title="Every attempt to send the link"
          tone={givenUp || undelivered ? 'bad' : deliveries.length === 0 ? 'warn' : 'ok'}
        >
          {deliveries.length === 0 ? (
            <Empty>
              Nothing tried to send this buyer their link. That is not a delivery that failed, it is
              a delivery that was never attempted.
            </Empty>
          ) : null}
          {givenUp ? (
            <Problem>
              This buyer paid and has been given up on. The drain hit its attempt limit and stopped,
              so nothing automatic will ever send this link. Only a resend below moves it.
            </Problem>
          ) : undelivered ? (
            <Problem>
              This buyer paid and has not received their link. Every attempt so far has failed, and
              the drain is still retrying.
            </Problem>
          ) : null}
          {deliveries.map((d) => (
            <div
              key={String(d.id)}
              className="border-t border-border pt-2 first:border-0 first:pt-0"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <Pill tone={deliveryTone(d.state)}>
                  {isAbandoned(d.state) ? 'abandoned · no retry' : d.state || 'no state'}
                </Pill>
                <span className="text-[12px] text-subtle">
                  {d.attempts === null || d.attempts === undefined
                    ? 'attempts not recorded'
                    : `${d.attempts} attempts`}
                </span>
              </div>
              {isAbandoned(d.state) ? (
                <div className="mt-2">
                  <Problem>
                    The drain tried the most times it is allowed to and stopped. Nothing will retry
                    this on its own — only a resend moves it.
                  </Problem>
                </div>
              ) : (
                <p className="mt-1 text-[13px] text-muted">{deliveryWords(d.state)}</p>
              )}
              <Row label="Queued">
                {d.createdAtUtc ? `${clock(d.createdAtUtc)} · ${ago(d.createdAtUtc)}` : ABSENT}
              </Row>
              <Row label="Sent">
                {d.sentAtUtc ? `${clock(d.sentAtUtc)} · ${ago(d.sentAtUtc)}` : 'not sent'}
              </Row>
              <Row label="Delivery row">
                <span className="wrap-any">{String(d.id)}</span>
              </Row>
              {d.lastError ? (
                <p className="wrap-any mt-1 font-mono text-[12px] text-bad-strong">{d.lastError}</p>
              ) : null}
              <ResendDelivery deliveryId={d.id} onDone={refresh} />
            </div>
          ))}
        </Card>
      ) : null}

      {data ? (
        <Card title="Other orders in the same payment">
          {siblings.length === 0 ? (
            <Empty>This payment created only this order.</Empty>
          ) : (
            <>
              <p className="text-[13px] text-muted">
                One payment can create several orders. A buyer chasing a missing link may be
                chasing one of these.
              </p>
              <div className="mt-2">
                {siblings.map((s) => (
                  <div key={s.id} className="border-t border-border py-2">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <Link className="wrap-any underline text-[13px]" href={`/orders/${encodeURIComponent(s.id)}`}>
                        {s.id}
                      </Link>
                      <span className="font-mono text-[13px]">
                        {money(s.amountPence, s.currency)}
                      </span>
                    </div>
                    <div className="wrap-any mt-1 font-mono text-[11px] text-subtle">
                      {s.packId || 'no pack id'}
                    </div>
                  </div>
                ))}
              </div>
              <Note>
                Each amount is shown in its own currency. They are not added together, because a
                total across currencies is not a number.
              </Note>
            </>
          )}
        </Card>
      ) : null}

      {data ? (
        <Card title="What the payment provider recorded">
          {audit.length === 0 ? (
            <Empty>No audit line for this order.</Empty>
          ) : (
            audit.map((a) => (
              <div key={String(a.id)} className="border-t border-border pt-2 first:border-0 first:pt-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[13px] text-muted">
                    {a.occurredAtUtc
                      ? `${clock(a.occurredAtUtc)} · ${ago(a.occurredAtUtc)}`
                      : ABSENT}
                  </span>
                  <span className="font-mono text-[15px]">
                    {money(a.amountMinorUnits, a.currency)}
                  </span>
                </div>
                <Row label="Product at the provider">
                  <span className="wrap-any">{a.providerProductId || ABSENT}</span>
                </Row>
                <Row label="Bought from">{a.country || ABSENT}</Row>
                <Row label="Line id">
                  <span className="wrap-any">{String(a.id)}</span>
                </Row>
              </div>
            ))
          )}
          <Note>
            The amount on each line is the whole transaction, as the payment provider recorded it.
            It is a different number from the per-pack split on the Revenue screen and the two are
            never added together.
          </Note>
          <Note>
            <Mono>read order --arg order_id={id || '…'}</Mono>
          </Note>
        </Card>
      ) : null}
    </Shell>
  );
}
