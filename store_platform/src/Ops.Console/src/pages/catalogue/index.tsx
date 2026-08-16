/**
 * Shelf — what is on sale right now, read from the store API.
 *
 * Two things this page is careful about.
 *
 * It reads `GET /catalog` on Store.Api, not `store/listings/*.json`. The local glob has measured
 * 77 files against 59 selling packs, so the directory has never been the shelf.
 *
 * That endpoint is the BUYER's endpoint, so it returns listed packs only. There is no internal
 * route that lists withdrawn packs. Rather than show a shorter list and let the operator assume
 * it is everything, the page says so and gives a box to look a withdrawn pack up by id.
 */
import Link from 'next/link';
import { useMemo, useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Row, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Item = {
  id: string;
  title: string | null;
  oneLine: string | null;
  price: string | null;
  pricePence: number | null;
  paymentProvider: string | null;
  providerPriceId: string | null;
  cardLine: string | null;
  headline: string | null;
  whoPays: string | null;
  effortTag: string | null;
  proofPoint: string | null;
  timeToFirstRevenue: string | null;
  sourceCount: number | null;
};

type CatalogueView = {
  origin: string;
  status: number;
  count: number;
  items: Item[];
  shows: string;
  note: string;
  source: string;
};

export default function Catalogue() {
  const { data, envelope, error, refresh } = useOps<CatalogueView>('catalogue');
  const [q, setQ] = useState('');
  const [lookup, setLookup] = useState('');

  const items = useMemo(() => {
    const rows = data?.items ?? [];
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) =>
      [r.id, r.title, r.oneLine, r.whoPays, r.cardLine]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(needle)),
    );
  }, [data, q]);

  return (
    <Shell title="Shelf" intro="What a buyer can pay for right now.">
      {error ? <Problem>{error}</Problem> : null}

      <Card
        title="On sale"
        right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
      >
        {!data ? (
          <Spinner what="reading the store API" />
        ) : (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-mono text-[24px]">{data.count}</span>
              <button onClick={refresh} className="tap text-[13px] text-muted underline">
                re-read
              </button>
            </div>
            <div className="mt-1 text-[13px] text-muted">
              packs listed on <span className="font-mono">{data.origin}</span>
            </div>
            <Note>{data.note}</Note>

            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="filter by title, id, buyer…"
              className="tap mt-3 w-full rounded-sm border border-border bg-surface px-3 text-[16px]"
            />
          </>
        )}
      </Card>

      <Card title="Look up a withdrawn pack">
        <p className="text-[13px] text-muted">
          A pack that is off the shelf is not in the list above, because the list is the buyer&apos;s
          view. Paste its id to open it and put it back.
        </p>
        <div className="mt-2 flex gap-2">
          <input
            value={lookup}
            onChange={(e) => setLookup(e.target.value)}
            placeholder="pack id"
            className="tap w-full rounded-sm border border-border bg-surface px-3 font-mono text-[16px]"
          />
          <Link
            href={lookup.trim() ? `/catalogue/${encodeURIComponent(lookup.trim())}` : '#'}
            aria-disabled={!lookup.trim()}
            className={`tap flex shrink-0 items-center rounded-sm border px-3 text-[14px] ${
              lookup.trim()
                ? 'border-action bg-action text-on-action'
                : 'pointer-events-none border-border text-faint'
            }`}
          >
            Open
          </Link>
        </div>
      </Card>

      {data && items.length === 0 ? (
        <Card>
          <Empty>
            {data.count === 0
              ? 'The store API answered with an empty shelf. That is a real answer, not a failed read — the read itself succeeded.'
              : 'Nothing matches that filter.'}
          </Empty>
        </Card>
      ) : null}

      {items.map((p) => (
        <Link
          key={p.id}
          href={`/catalogue/${encodeURIComponent(p.id)}`}
          className="block rounded-md border border-border bg-surface2 px-4 py-3 hover:bg-surface3"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-[15px] font-[520]">{p.title || 'untitled'}</span>
            <Pill tone="ok">{p.price || 'no price'}</Pill>
          </div>
          {p.oneLine ? <p className="mt-1 text-[13px] text-muted">{p.oneLine}</p> : null}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {p.whoPays ? <Pill tone="mute">{p.whoPays}</Pill> : null}
            {p.effortTag ? <Pill tone="mute">{p.effortTag}</Pill> : null}
            {p.sourceCount ? <Pill tone="mute">{p.sourceCount} sources</Pill> : null}
            {p.providerPriceId ? null : <Pill tone="warn">no Stripe price id</Pill>}
          </div>
          <div className="wrap-any mt-2 font-mono text-[11px] text-subtle">{p.id}</div>
        </Link>
      ))}

      {data ? (
        <Card title="Where this came from">
          <Row label="Source">{data.source}</Row>
          <Row label="Shows">{data.shows}</Row>
          <Row label="HTTP">{data.status}</Row>
        </Card>
      ) : null}
    </Shell>
  );
}
