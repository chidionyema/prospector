/**
 * Disputes and refunds — the money a buyer has pulled back, or is trying to.
 *
 * TWO THINGS THIS SCREEN REFUSES TO IMPLY.
 *
 * The figure is money AT RISK, not money returned. It comes from SalesAudit, which records what
 * the sale was worth. What was actually refunded is not recorded anywhere in this system, so no
 * label here says "refunded" against an amount. Calling it that would put a number on a question
 * nobody has measured.
 *
 * The dates are SALE dates, not reversal dates. Nothing timestamps the reversal, so this list
 * cannot be ordered by how urgent a dispute is, and the screen says so where the operator will
 * read it rather than in a comment. An operator who assumes the top of the list is the most urgent
 * answers the oldest dispute last.
 *
 * Currencies are never combined here either. One line per currency, always.
 */
import Link from 'next/link';
import { useState } from 'react';

import OrderRow from '@/components/OrderRow';
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Row, Spinner, Stat } from '@/components/ui';
import { addCounts, money, perCurrency } from '@/lib/money';
import type { Order } from '@/lib/shop';
import { useOps } from '@/lib/useOps';

type StatusCount = { status: string | null; orders: number | null };
type Gross = { currency: string | null; grossMinorUnits: number | null; transactions: number | null };

type DisputesView = {
  reachable?: boolean;
  error?: string | null;
  as_of_utc?: string | null;
  days: number | null;
  date_basis: string | null;
  counts: StatusCount[] | null;
  order_count: number | null;
  by_currency: Gross[] | null;
  entitlements_revoked: number | null;
  orders: Order[] | null;
  warnings: string[];
  source?: string;
};

const WINDOWS = [30, 90, 180];

function statusTone(status: string | null): 'bad' | 'warn' | 'mute' {
  const s = (status ?? '').toLowerCase();
  if (s === 'disputed') return 'bad';
  if (s === 'refunded' || s === 'partiallyrefunded') return 'warn';
  return 'mute';
}

export default function Disputes() {
  const [days, setDays] = useState(90);
  const { data, envelope, error, refresh } = useOps<DisputesView>('disputes', { days });

  const counts = data?.counts ?? [];
  const orders = data?.orders ?? [];
  const atRisk = perCurrency(
    (data?.by_currency ?? []).map((r) => ({
      currency: r.currency,
      minorUnits: r.grossMinorUnits,
    })),
  );

  return (
    <Shell
      title="Disputes"
      intro="Money a buyer has pulled back, or is trying to."
    >
      {error ? <Problem>{error}</Problem> : null}
      {data?.reachable === false ? (
        <Problem>
          {data.error ||
            'The dispute list could not be read. Nothing here says there are no disputes; it says we cannot tell.'}
        </Problem>
      ) : null}
      {(data?.warnings ?? []).map((w) => (
        <Problem key={w}>{w}</Problem>
      ))}

      <Card
        title="What is at risk"
        tone={data && orders.length > 0 ? 'warn' : 'plain'}
        right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
      >
        {!data ? (
          <Spinner what="disputes and refunds" />
        ) : (
          <>
            <div className="flex flex-wrap gap-1">
              {WINDOWS.map((w) => (
                <button
                  key={w}
                  type="button"
                  onClick={() => setDays(w)}
                  aria-pressed={days === w}
                  className={`tap inline-flex items-center rounded-sm border px-3 text-[13px] ${
                    days === w
                      ? 'border-action bg-action text-on-action'
                      : 'border-border bg-surface text-muted hover:bg-surface3'
                  }`}
                >
                  {w} days
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

            {atRisk.length === 0 ? (
              <Note>
                No amount was recorded against a disputed or refunded order in this window. That is
                an empty reading, not a figure of zero.
              </Note>
            ) : (
              <>
                <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-3">
                  {atRisk.map((t) => {
                    const txns = addCounts(
                      (data.by_currency ?? [])
                        .filter((r) => (r.currency ?? '').toUpperCase() === t.currency)
                        .map((r) => r.transactions),
                    );
                    return (
                      <Stat
                        key={t.currency}
                        label={`at risk (${t.currency})`}
                        value={t.minorUnits === null ? null : money(t.minorUnits, t.currency)}
                        tone={t.minorUnits ? 'warn' : 'plain'}
                        note={
                          t.minorUnits === null
                            ? 'an amount in this currency was not recorded'
                            : txns === null
                              ? 'sales count not recorded'
                              : `${txns} sales`
                        }
                      />
                    );
                  })}
                </div>
                {atRisk.length > 1 ? (
                  <Note>
                    {atRisk.length} currencies, {atRisk.length} figures. They are never added
                    together.
                  </Note>
                ) : null}
              </>
            )}

            <div className="mt-3 rounded-sm border border-warn/50 bg-warn-bg px-3 py-2 text-[13px]">
              <strong className="font-[560]">This is what the sales were worth, not what came back.</strong>
              <p className="mt-1 text-muted">
                The figure is the value of the disputed and refunded sales. How much was actually
                returned to the buyer is not recorded anywhere in this system, so nothing here can
                tell you what the shop lost.
              </p>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat
                label="orders affected"
                value={data.order_count}
                note={data.order_count === null ? 'the store did not report a count' : null}
              />
              <Stat
                label="downloads revoked"
                value={data.entitlements_revoked}
                note={
                  data.entitlements_revoked === null
                    ? 'not measured'
                    : 'these buyers can no longer download'
                }
              />
              <Stat label="window" value={data.days ?? days} unit="days" />
            </div>
          </>
        )}
      </Card>

      {data ? (
        <Card title="How the orders were reversed">
          {counts.length === 0 ? (
            <Empty>No disputed or refunded order in this window.</Empty>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {counts.map((c) => (
                <Pill key={c.status ?? 'unknown'} tone={statusTone(c.status)}>
                  {c.status || 'no status'} ·{' '}
                  {c.orders === null || c.orders === undefined ? 'not counted' : c.orders}
                </Pill>
              ))}
            </div>
          )}
        </Card>
      ) : null}

      {data ? (
        <Card title="You cannot tell which of these is most urgent" tone="warn">
          <p className="text-[13px] text-muted">
            {data.date_basis ||
              'The dates below are the dates of SALE. Nothing records when the dispute or refund happened.'}
          </p>
          <p className="mt-2 text-[13px] text-muted">
            So this list cannot be sorted by how long a dispute has been open. Reading it top-down
            and working in that order will answer the oldest dispute last. Card networks give a
            fixed window to respond, and it starts at the dispute, not at the sale.
          </p>
          <Note>
            Closing this gap needs a stored reversal timestamp and a migration. It is tracked as{' '}
            <span className="font-mono">dispute-clock</span> on the{' '}
            <Link className="underline" href="/money">
              Money
            </Link>{' '}
            screen.
          </Note>
        </Card>
      ) : null}

      {data && orders.length === 0 ? (
        <Card>
          <Empty>
            No order was disputed or refunded in this window. The read succeeded, so this is a real
            answer.
          </Empty>
        </Card>
      ) : null}

      {orders.length > 0 ? (
        <Card title={`${orders.length} reversed ${orders.length === 1 ? 'order' : 'orders'}`}>
          <p className="text-[13px] text-muted">
            Every date below is the date the order was <strong className="font-[560]">sold</strong>.
          </p>
          <Note>
            {data?.date_basis || 'order created; the reversal itself is not timestamped anywhere'}
          </Note>
        </Card>
      ) : null}

      {orders.map((o) => (
        <OrderRow key={o.id} order={o} dateWord="sold" />
      ))}

      {data ? (
        <Card title="Where this came from">
          <Row label="Read">read disputes --arg days={data.days ?? days}</Row>
          <Row label="Source">{data.source || 'not recorded'}</Row>
          <Row label="Store read at">{data.as_of_utc || 'not recorded'}</Row>
        </Card>
      ) : null}
    </Shell>
  );
}
