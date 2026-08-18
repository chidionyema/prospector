/**
 * Revenue — what the shop took, today and over a window.
 *
 * The rule this screen exists to obey: THERE IS NO SINGLE REVENUE NUMBER. The shop sells in more
 * than one currency, and £40 plus $40 is not 80 of anything. Every figure on this page is one
 * currency, on its own line, with its own symbol. `lib/money.ts` enforces it — `addMinorUnits`
 * throws when handed two currencies, and only `perCurrency` may reduce a mixed list.
 *
 * The second rule: an unmeasured figure says so. A currency whose total is missing renders "not
 * recorded", never £0.00, because a blank tile reads as "a quiet day" when it means "the read
 * failed".
 */
import { useMemo, useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Mono, Note, Pill, Problem, Row, Spinner, Stat } from '@/components/ui';
import { addCounts, money, perCurrency } from '@/lib/money';
import { ABSENT } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Gross = { currency: string | null; grossMinorUnits: number | null; transactions: number | null };
type DayGross = Gross & { date: string | null };
type PackSales = {
  packId: string | null;
  packTitle: string | null;
  currency: string | null;
  units: number | null;
  splitMinorUnits: number | null;
  refunded: number | null;
  disputed: number | null;
};
type StatusCount = { status: string | null; orders: number | null };

type SalesView = {
  today: Gross[];
  byCurrency: Gross[];
  byDay: DayGross[];
  byPack: PackSales[];
  orderStatuses: StatusCount[];
  orderCount: number | null;
  days: number | null;
  dayBoundary: string | null;
  warnings: string[];
};

const WINDOWS = [7, 30, 90];

/** One block of per-currency figures. Two currencies is two tiles, never one sum. */
function GrossTiles({ rows, what }: { rows: Gross[]; what: string }) {
  const totals = perCurrency(
    rows.map((r) => ({ currency: r.currency, minorUnits: r.grossMinorUnits })),
  );
  if (totals.length === 0) {
    return (
      <Note>
        Nothing was recorded for {what}. This is an empty reading, not a figure of zero — if a
        currency were taken and not measured, it would show here as not recorded.
      </Note>
    );
  }
  return (
    <>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        {totals.map((t) => {
          const txns = addCounts(
            rows.filter((r) => (r.currency ?? '').toUpperCase() === t.currency).map((r) => r.transactions),
          );
          return (
            <Stat
              key={t.currency}
              label={t.currency}
              value={t.minorUnits === null ? null : money(t.minorUnits, t.currency)}
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
      {totals.length > 1 ? (
        <Note>
          {totals.length} currencies, {totals.length} figures. They are never added together.
        </Note>
      ) : null}
    </>
  );
}

export default function Revenue() {
  const [days, setDays] = useState(30);
  const { data, envelope, error, refresh } = useOps<SalesView>('sales', { days });

  const byDay = useMemo(() => {
    const grouped = new Map<string, DayGross[]>();
    for (const r of data?.byDay ?? []) {
      const key = r.date ?? ABSENT;
      grouped.set(key, [...(grouped.get(key) ?? []), r]);
    }
    return [...grouped.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [data]);

  const packs = data?.byPack ?? [];

  return (
    <Shell title="Revenue" intro="What the shop took, today and over a window.">
      {error ? <Problem>{error}</Problem> : null}
      {(data?.warnings ?? []).map((w) => (
        <Problem key={w}>{w}</Problem>
      ))}

      <Card
        title="Taken today"
        right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
      >
        {!data ? <Spinner what="the shop's sales" /> : <GrossTiles rows={data.today} what="today" />}
        {data?.dayBoundary ? (
          <Row label="A day starts at">
            <Mono>{data.dayBoundary}</Mono>
          </Row>
        ) : null}
      </Card>

      <Card title={`Taken over ${data?.days ?? days} days`}>
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
        <div className="mt-3">
          {!data ? <Spinner what="the window" /> : <GrossTiles rows={data.byCurrency} what="this window" />}
        </div>
        {data ? (
          <div className="mt-3">
            <Stat
              label="orders in the window"
              value={data.orderCount}
              note={data.orderCount === null ? 'the store did not report a count' : null}
            />
          </div>
        ) : null}
      </Card>

      {data ? (
        <Card title="Where the orders stand">
          {data.orderStatuses.length === 0 ? (
            <Empty>No order status was reported for this window.</Empty>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {data.orderStatuses.map((s) => (
                <Pill key={s.status ?? 'unknown'} tone="mute">
                  {s.status || 'no status'} ·{' '}
                  {s.orders === null || s.orders === undefined ? 'not counted' : s.orders}
                </Pill>
              ))}
            </div>
          )}
        </Card>
      ) : null}

      {data ? (
        <Card title="Day by day">
          {byDay.length === 0 ? (
            <Empty>No day in this window has a sale recorded against it.</Empty>
          ) : (
            byDay.map(([date, rows]) => (
              <div key={date} className="border-b border-border py-2 last:border-0">
                <div className="text-[13px] font-[520]">{date}</div>
                <div className="mt-1 flex flex-col gap-0.5">
                  {perCurrency(
                    rows.map((r) => ({ currency: r.currency, minorUnits: r.grossMinorUnits })),
                  ).map((t) => {
                    const txns = addCounts(
                      rows
                        .filter((r) => (r.currency ?? '').toUpperCase() === t.currency)
                        .map((r) => r.transactions),
                    );
                    return (
                      <div key={t.currency} className="flex flex-wrap justify-between gap-2">
                        <span className="text-[13px] text-muted">
                          {txns === null ? 'sales not counted' : `${txns} sales`} · {t.currency}
                        </span>
                        <span className="font-mono text-[13px]">
                          {money(t.minorUnits, t.currency)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </Card>
      ) : null}

      {data ? (
        <Card title="By pack">
          {packs.length === 0 ? (
            <Empty>No pack sold in this window.</Empty>
          ) : (
            packs.map((p, i) => (
              <div
                key={`${p.packId ?? 'no-id'}-${p.currency ?? 'no-ccy'}-${i}`}
                className="border-b border-border py-2 last:border-0"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="min-w-0 text-[14px] font-[520]">
                    {p.packTitle || 'untitled pack'}
                  </span>
                  <span className="font-mono text-[14px]">
                    {money(p.splitMinorUnits, p.currency)}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <Pill tone="mute">
                    {p.units === null || p.units === undefined ? 'units not counted' : `${p.units} sold`}
                  </Pill>
                  {p.refunded ? <Pill tone="warn">{p.refunded} refunded</Pill> : null}
                  {p.disputed ? <Pill tone="bad">{p.disputed} disputed</Pill> : null}
                  {p.currency ? <Pill tone="mute">{p.currency}</Pill> : null}
                </div>
                <div className="wrap-any mt-1 font-mono text-[11px] text-subtle">
                  {p.packId || 'no pack id'}
                </div>
              </div>
            ))
          )}
          <Note>
            The figure beside each pack is the split the store recorded for it, in that pack&apos;s
            own currency. A pack sold in two currencies appears once per currency.
          </Note>
        </Card>
      ) : null}
    </Shell>
  );
}
