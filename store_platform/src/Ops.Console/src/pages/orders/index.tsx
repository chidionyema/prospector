/**
 * Orders — who bought what, and did they get it.
 *
 * Two decisions worth stating.
 *
 * The list is CARDS, not a table. A table of nine columns needs 900px and the founder reads this
 * on a 390px phone inside Telegram, where the fix has twice been a sideways scroll nobody can see
 * the edge of. Every long token here — the buyer's email, the `pi_…` transaction id, an error
 * string — is wrapped, because one unbroken 60-character string is all it takes to push the whole
 * page off the side.
 *
 * The filters are APPLIED, not live. Each read spawns a Python process, so a filter that re-read
 * on every keystroke would spawn one per keystroke.
 */
import { useState } from 'react';

import OrderRow from '@/components/OrderRow';
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Mono, Note, Problem, Row, Spinner, Stat } from '@/components/ui';
import { money, perCurrency } from '@/lib/money';
import type { Order } from '@/lib/shop';
import { useOps } from '@/lib/useOps';

type OrdersView = {
  orders: Order[];
  total: number | null;
  limit: number | null;
  offset: number | null;
  warnings: string[];
};

const PAGE = 25;

type Filters = { q: string; status: string; packId: string; offset: number };
const NO_FILTERS: Filters = { q: '', status: '', packId: '', offset: 0 };

export default function Orders() {
  // `applied` is what the engine is asked for; `form` is what the operator is typing.
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);
  const [form, setForm] = useState<Filters>(NO_FILTERS);

  const { data, envelope, error, refresh } = useOps<OrdersView>('orders', {
    q: applied.q,
    status: applied.status,
    packId: applied.packId,
    limit: PAGE,
    offset: applied.offset,
  });

  const rows = data?.orders ?? [];
  const total = data?.total ?? null;
  const offset = data?.offset ?? applied.offset;
  const shown = rows.length;
  // A per-currency total of THIS page only, and labelled as such. There is deliberately no single
  // "total revenue" figure: two currencies means two lines, always.
  const pageTotals = perCurrency(
    rows.map((o) => ({ currency: o.currency, minorUnits: o.amountMinorUnits })),
  );

  const apply = (next: Filters) => {
    setForm(next);
    setApplied(next);
  };

  return (
    <Shell title="Orders" intro="Who bought what, and whether they got it.">
      {error ? <Problem>{error}</Problem> : null}
      {(data?.warnings ?? []).map((w) => (
        <Problem key={w}>{w}</Problem>
      ))}

      <Card title="Find an order" right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            apply({ ...form, offset: 0 });
          }}
        >
          <label className="block text-[12px] uppercase tracking-[0.06em] text-subtle">
            Buyer, pack or order id
          </label>
          <input
            value={form.q}
            onChange={(e) => setForm({ ...form, q: e.target.value })}
            placeholder="an email, a title, an id"
            className="tap mt-1 w-full rounded-sm border border-border bg-surface px-3 text-[16px]"
          />

          <label className="mt-3 block text-[12px] uppercase tracking-[0.06em] text-subtle">
            Pack id
          </label>
          <input
            value={form.packId}
            onChange={(e) => setForm({ ...form, packId: e.target.value })}
            placeholder="only orders for one pack"
            className="tap mt-1 w-full rounded-sm border border-border bg-surface px-3 font-mono text-[16px]"
          />

          <div className="mt-3 flex flex-wrap gap-1">
            {['', 'paid', 'refunded', 'disputed', 'pending'].map((s) => (
              <button
                key={s || 'any'}
                type="button"
                onClick={() => apply({ ...form, status: s, offset: 0 })}
                aria-pressed={applied.status === s}
                className={`tap inline-flex items-center rounded-sm border px-3 text-[13px] ${
                  applied.status === s
                    ? 'border-action bg-action text-on-action'
                    : 'border-border bg-surface text-muted hover:bg-surface3'
                }`}
              >
                {s || 'any status'}
              </button>
            ))}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="submit"
              className="tap inline-flex items-center rounded-sm border border-action bg-action px-3 text-[14px] font-[520] text-on-action"
            >
              Search
            </button>
            <button
              type="button"
              onClick={() => apply(NO_FILTERS)}
              className="tap inline-flex items-center rounded-sm border border-border-control bg-surface px-3 text-[14px] text-text hover:bg-surface3"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={refresh}
              className="tap inline-flex items-center px-2 text-[13px] text-muted underline"
            >
              re-read
            </button>
          </div>
        </form>
      </Card>

      {!data ? (
        <Card>
          <Spinner what="the shop's orders" />
        </Card>
      ) : null}

      {data ? (
        <Card title="This page">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Stat label="orders shown" value={shown} />
            <Stat
              label="orders matching"
              value={total}
              note={total === null ? 'the store did not report a count' : null}
            />
            <Stat label="starting at" value={offset} />
          </div>
          {pageTotals.length === 0 ? (
            <Note>
              No amount on this page carried a currency, so there is nothing to add up. That is a
              missing field, not a page of free orders.
            </Note>
          ) : (
            <>
              <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-3">
                {pageTotals.map((t) => (
                  <Stat
                    key={t.currency}
                    label={`taken on this page (${t.currency})`}
                    value={t.minorUnits === null ? null : money(t.minorUnits, t.currency)}
                    note={t.minorUnits === null ? 'an order on this page has no amount' : null}
                  />
                ))}
              </div>
              {pageTotals.length > 1 ? (
                <Note>
                  This page has orders in {pageTotals.length} currencies. They are shown as separate
                  figures and are never added together.
                </Note>
              ) : null}
            </>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={offset <= 0}
              onClick={() => apply({ ...applied, offset: Math.max(0, offset - PAGE) })}
              className="tap inline-flex items-center rounded-sm border border-border-control bg-surface px-3 text-[14px] disabled:opacity-45"
            >
              Newer
            </button>
            <button
              type="button"
              disabled={shown < PAGE}
              onClick={() => apply({ ...applied, offset: offset + PAGE })}
              className="tap inline-flex items-center rounded-sm border border-border-control bg-surface px-3 text-[14px] disabled:opacity-45"
            >
              Older
            </button>
          </div>
        </Card>
      ) : null}

      {data && rows.length === 0 ? (
        <Card>
          <Empty>
            No order matches. The read itself succeeded, so this is an empty result rather than a
            failed measurement.
          </Empty>
        </Card>
      ) : null}

      {rows.map((o) => (
        <OrderRow key={o.id} order={o} />
      ))}

      {data ? (
        <Card title="What this list is">
          <Row label="Page size">{PAGE}</Row>
          <Row label="Filter">
            <Mono>
              {[
                applied.q ? `q=${applied.q}` : null,
                applied.status ? `status=${applied.status}` : null,
                applied.packId ? `packId=${applied.packId}` : null,
              ]
                .filter(Boolean)
                .join(' ') || 'none'}
            </Mono>
          </Row>
          <Row label="Read">read orders</Row>
        </Card>
      ) : null}
    </Shell>
  );
}
