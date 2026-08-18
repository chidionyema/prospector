/**
 * Delivery — who paid and has not received their link.
 *
 * This is the one screen where a wrong zero costs a refund. If the count of undelivered orders
 * cannot be measured, the page says so in words; it never paints an unmeasured count as "nobody is
 * waiting". The headline is a sentence for that reason, not a tile.
 *
 * ABANDONED OUTRANKS FAILED, and the screen has to make that obvious. A failed delivery is still
 * being retried by the drain. An abandoned one hit `Delivery:MaxAttempts` and the drain stopped:
 * that buyer paid, holds an entitlement, and will never be sent their link by any automatic
 * process. So abandoned rows sort first, carry their own red banner, and are the only ones the
 * headline calls out by name.
 *
 * TWO IDS, AND THEY ARE NOT INTERCHANGEABLE. A row's `id` is the delivery row — it is what
 * `deliveries.resend` takes. `orderId` is the order it belongs to, and it is what the "Order" link
 * must use. They are different numbers, so linking `id` sends the operator to a different buyer's
 * order.
 *
 * The error strings here are the longest unbroken tokens in the console — an SMTP failure or a
 * provider stack trace on one line. They are wrapped rather than truncated: a truncated error is
 * an error nobody can act on, and an unwrapped one pushes a 390px page sideways.
 */
import Link from 'next/link';
import { useState } from 'react';

import ResendDelivery from '@/components/ResendDelivery';
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Row, Spinner, Stat } from '@/components/ui';
import { DELIVERY_STATES, deliverySeverity, deliveryTone, deliveryWords, isAbandoned } from '@/lib/shop';
import { ABSENT, ago, clock, duration } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Waiting = {
  id: string | number;
  orderId: string | number | null;
  packId: string | null;
  packTitle: string | null;
  buyerEmail: string | null;
  createdAtUtc: string | null;
  sentAtUtc: string | null;
  ageMinutes: number | null;
  attempts: number | null;
  lastError: string | null;
  state: string | null;
};

type DeliveriesView = {
  reachable?: boolean;
  error?: string | null;
  state?: string | null;
  maxAttempts?: number | null;
  counts: {
    sent: number | null;
    pending: number | null;
    failed: number | null;
    abandoned: number | null;
    undelivered: number | null;
  } | null;
  deliveries: Waiting[] | null;
  warnings: string[];
};

const FIRST_PAGE = 50;

/** `Card` knows four tones and "mute" is not one of them. An unknown state gets no colour. */
function cardTone(state: string | null | undefined): 'plain' | 'warn' | 'bad' {
  const t = deliveryTone(state);
  return t === 'warn' || t === 'bad' ? t : 'plain';
}

/**
 * The headline sentence. An unmeasured count is words, never a zero, and an abandoned count gets
 * its own sentence because it is the only state nothing will retry.
 */
function headline(
  undelivered: number | null | undefined,
  abandoned: number | null | undefined,
): { text: string; also: string | null; tone: 'ok' | 'warn' | 'bad' } {
  const stuck =
    abandoned !== null && abandoned !== undefined && Number.isFinite(abandoned) && abandoned > 0
      ? abandoned === 1
        ? '1 of them was given up on. Nothing will retry it without a resend.'
        : `${abandoned} of them were given up on. Nothing will retry those without a resend.`
      : null;

  if (undelivered === null || undelivered === undefined || !Number.isFinite(undelivered)) {
    return {
      text: 'We could not measure how many buyers are waiting. This is a failed reading, not a quiet queue.',
      also: stuck,
      tone: 'warn',
    };
  }
  if (undelivered === 0) {
    return { text: 'Every buyer who paid has received their link.', also: stuck, tone: 'ok' };
  }
  if (undelivered === 1) {
    return { text: '1 buyer has paid and not received their link.', also: stuck, tone: 'bad' };
  }
  return {
    text: `${undelivered} buyers have paid and not received their link.`,
    also: stuck,
    tone: 'bad',
  };
}

export default function Delivery() {
  const [state, setState] = useState('all');
  const [limit, setLimit] = useState(FIRST_PAGE);
  const { data, envelope, error, refresh } = useOps<DeliveriesView>('deliveries', { state, limit });

  const counts = data?.counts ?? null;
  // Worst first. An operator scrolling this list should hit the buyers nothing will retry before
  // the ones the drain is still working on.
  const rows = [...(data?.deliveries ?? [])].sort(
    (a, b) => deliverySeverity(b.state) - deliverySeverity(a.state),
  );
  const head = headline(counts?.undelivered, counts?.abandoned);
  const maybeMore = rows.length >= limit;

  const pick = (s: string) => {
    setState(s);
    setLimit(FIRST_PAGE);
  };

  return (
    <Shell title="Delivery" intro="Who paid and has not received their link.">
      {error ? <Problem>{error}</Problem> : null}
      {data?.reachable === false ? (
        <Problem>
          {data.error ||
            'The delivery outbox could not be read. Nothing here says a buyer was served; it says we cannot tell.'}
        </Problem>
      ) : null}
      {(data?.warnings ?? []).map((w) => (
        <Problem key={w}>{w}</Problem>
      ))}

      <Card
        title="Where deliveries stand"
        tone={data ? head.tone : 'plain'}
        right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
      >
        {!data ? (
          <Spinner what="the delivery queue" />
        ) : (
          <>
            <p className="text-[15px] font-[520]">{head.text}</p>
            {head.also ? (
              <p className="mt-1 text-[14px] font-[520] text-bad-strong">{head.also}</p>
            ) : null}
            {counts === null ? (
              <Note>
                The store returned no counts at all, so none of the figures below could be read.
              </Note>
            ) : (
              <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-3">
                <Stat
                  label="waiting"
                  value={counts.undelivered}
                  tone={counts.undelivered ? 'bad' : 'plain'}
                  note={
                    counts.undelivered === null
                      ? 'not measured'
                      : 'not sent, failed and abandoned together'
                  }
                />
                <Stat
                  label="given up on"
                  value={counts.abandoned}
                  tone={counts.abandoned ? 'bad' : 'plain'}
                  note={
                    counts.abandoned === null
                      ? 'not measured'
                      : 'nothing will retry these on its own'
                  }
                />
                <Stat
                  label="failed"
                  value={counts.failed}
                  tone={counts.failed ? 'warn' : 'plain'}
                  note={counts.failed === null ? 'not measured' : 'still being retried'}
                />
                <Stat
                  label="not sent yet"
                  value={counts.pending}
                  tone={counts.pending ? 'warn' : 'plain'}
                  note={counts.pending === null ? 'not measured' : null}
                />
                <Stat
                  label="sent"
                  value={counts.sent}
                  tone="ok"
                  note={counts.sent === null ? 'not measured' : null}
                />
              </div>
            )}
            {typeof data.maxAttempts === 'number' ? (
              <Row label="Attempts before the drain gives up">{data.maxAttempts}</Row>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-1">
              {DELIVERY_STATES.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => pick(s)}
                  aria-pressed={state === s}
                  className={`tap inline-flex items-center rounded-sm border px-3 text-[13px] ${
                    state === s
                      ? 'border-action bg-action text-on-action'
                      : 'border-border bg-surface text-muted hover:bg-surface3'
                  }`}
                >
                  {s === 'all' ? 'everything' : s}
                </button>
              ))}
              <button
                type="button"
                onClick={refresh}
                className="tap inline-flex items-center px-2 text-[13px] text-muted underline"
              >
                re-read
              </button>
            </div>
          </>
        )}
      </Card>

      {!data ? null : rows.length === 0 ? (
        <Card>
          <Empty>
            Nothing matches this filter. The read succeeded, so this is an empty list rather than a
            failed measurement.
          </Empty>
        </Card>
      ) : null}

      {rows.map((d) => (
        <Card key={String(d.id)} tone={cardTone(d.state)}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="min-w-0 text-[15px] font-[520]">{d.packTitle || 'untitled pack'}</span>
            <Pill tone={deliveryTone(d.state)}>
              {isAbandoned(d.state) ? 'abandoned · no retry' : d.state || 'no state'}
            </Pill>
          </div>
          <div className="wrap-any mt-1 text-[13px] text-muted">{d.buyerEmail || ABSENT}</div>
          {isAbandoned(d.state) ? (
            <div className="mt-2">
              <Problem>
                This buyer paid and will never be sent their link by anything automatic. The drain
                tried the most times it is allowed to and stopped. Only a resend moves it.
              </Problem>
            </div>
          ) : (
            <p className="mt-1 text-[13px] text-muted">{deliveryWords(d.state)}</p>
          )}
          <div className="mt-2">
            <Row label="Waiting for">
              {d.ageMinutes === null || d.ageMinutes === undefined
                ? ABSENT
                : duration(d.ageMinutes * 60)}
            </Row>
            <Row label="Paid at">
              {d.createdAtUtc ? `${clock(d.createdAtUtc)} · ${ago(d.createdAtUtc)}` : ABSENT}
            </Row>
            <Row label="Sent at">
              {d.sentAtUtc ? `${clock(d.sentAtUtc)} · ${ago(d.sentAtUtc)}` : 'not sent'}
            </Row>
            <Row label="Attempts">
              {d.attempts === null || d.attempts === undefined ? ABSENT : d.attempts}
            </Row>
            <Row label="Order">
              {d.orderId === null || d.orderId === undefined || d.orderId === '' ? (
                ABSENT
              ) : (
                <Link
                  className="wrap-any underline"
                  href={`/orders/${encodeURIComponent(String(d.orderId))}`}
                >
                  {String(d.orderId)}
                </Link>
              )}
            </Row>
            <Row label="Delivery row">
              <span className="wrap-any">{String(d.id)}</span>
            </Row>
            <Row label="Pack">
              <span className="wrap-any">{d.packId || ABSENT}</span>
            </Row>
          </div>
          {d.lastError ? (
            <p className="wrap-any mt-2 font-mono text-[12px] text-bad-strong">{d.lastError}</p>
          ) : null}
          <ResendDelivery deliveryId={d.id} onDone={refresh} />
        </Card>
      ))}

      {data && maybeMore ? (
        <Card>
          <p className="text-[13px] text-muted">
            Showing the first {limit}. There may be more behind this filter.
          </p>
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setLimit(limit + FIRST_PAGE)}
              className="tap inline-flex items-center rounded-sm border border-border-control bg-surface px-3 text-[14px] hover:bg-surface3"
            >
              Show {FIRST_PAGE} more
            </button>
          </div>
        </Card>
      ) : null}
    </Shell>
  );
}
