/**
 * One pack: what the shelf shows, whether it is on sale, and who moved its price.
 *
 * Price is READ ONLY here, and that is a fence rather than an omission. `prospector/bridge.py`
 * mints the Stripe Price and writes the catalogue row as one `PriceDecision`, so the two cannot
 * drift; a web form that wrote one of them would charge a buyer one number and fulfil against
 * another. The flow is specified in docs/ADMIN_CONSOLE_PROGRAM.md §7 and is not implemented.
 *
 * The one write on this page is the listing bit, through `PATCH /internal/catalog/{id}/listing`,
 * which is the only endpoint that can change it without also rewriting the Stripe ids.
 */
import { useRouter } from 'next/router';
import { useState } from 'react';

import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Row, Scroll, Spinner } from '@/components/ui';
import { ABSENT, ago, clock } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Pack = Record<string, unknown> & {
  id?: string;
  title?: string | null;
  oneLine?: string | null;
  price?: string | null;
  pricePence?: number | null;
  paymentProvider?: string | null;
  providerPriceId?: string | null;
  dossierRef?: string | null;
  headline?: string | null;
  subhead?: string | null;
  proofPoint?: string | null;
  whoPays?: string | null;
  effortTag?: string | null;
  timeToFirstRevenue?: string | null;
  qaVerdictSummary?: string | null;
  market?: string | null;
  audience?: string | null;
  sourceCount?: number | null;
  verifiedAt?: string | null;
  sector?: string | null;
};

type PriceChange = {
  id: number;
  fromPence: number;
  toPence: number;
  minBillablePence: number | null;
  providerPriceId: string | null;
  reason: string | null;
  actor: string | null;
  rationaleRef: string | null;
  createdAt: string;
};

type PackView = {
  id: string;
  status: number;
  pack: Pack | null;
  listed: boolean;
  listed_note: string;
  exists: boolean | null;
  price_history: {
    packId: string;
    currentPricePence: number;
    currentMinBillablePence: number | null;
    publishedAt: string;
    originPricePence: number;
    changeCount: number;
    continuous: boolean;
    truncated: boolean;
    history: PriceChange[];
  } | null;
  price_history_status?: number;
  price_history_error?: string;
  price_note: string;
};

const money = (pence: number | null | undefined) =>
  pence === null || pence === undefined ? ABSENT : `£${(pence / 100).toFixed(2)}`;

export default function PackDetail() {
  const router = useRouter();
  const id = typeof router.query.id === 'string' ? router.query.id : '';
  const { data, envelope, error, refresh } = useOps<PackView>(id ? 'pack' : null, { id });
  const [reason, setReason] = useState('');

  const pack = data?.pack ?? null;
  const hist = data?.price_history ?? null;

  return (
    <Shell title="Pack" intro={id}>
      {error ? <Problem>{error}</Problem> : null}
      {!data && id ? (
        <Card>
          <Spinner what="reading the store API" />
        </Card>
      ) : null}

      {data ? (
        <Card
          title={pack?.title || (data.exists === false ? 'No such pack' : 'Withdrawn pack')}
          tone={data.listed ? 'ok' : data.exists === false ? 'bad' : 'warn'}
          right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
        >
          <div className="flex flex-wrap gap-1.5">
            <Pill tone={data.listed ? 'ok' : 'warn'}>
              {data.listed ? 'on the shelf' : 'not on the shelf'}
            </Pill>
            {data.exists === false ? <Pill tone="bad">no pack row</Pill> : null}
            {pack?.market ? <Pill tone="mute">{String(pack.market)}</Pill> : null}
            {pack?.sector ? <Pill tone="mute">{String(pack.sector)}</Pill> : null}
          </div>
          <Note>{data.listed_note}</Note>
          {pack?.oneLine ? <p className="mt-2 text-[14px]">{String(pack.oneLine)}</p> : null}
          <div className="wrap-any mt-2 font-mono text-[11px] text-subtle">{data.id}</div>
        </Card>
      ) : null}

      {data ? (
        <Card title="Price" tone="plain">
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-[28px]">
              {pack?.price ? String(pack.price) : money(hist?.currentPricePence)}
            </span>
            {pack?.paymentProvider ? (
              <Pill tone="mute">{String(pack.paymentProvider)}</Pill>
            ) : null}
          </div>
          <div className="mt-2">
            <Row label="Floor (min billable)">{money(hist?.currentMinBillablePence)}</Row>
            <Row label="Stripe price id">
              {pack?.providerPriceId ? (
                <span className="wrap-any font-mono">{String(pack.providerPriceId)}</span>
              ) : (
                ABSENT
              )}
            </Row>
            <Row label="First listed">
              {hist?.publishedAt ? `${clock(hist.publishedAt)} · ${ago(hist.publishedAt)}` : ABSENT}
            </Row>
            <Row label="Price when first listed">{money(hist?.originPricePence)}</Row>
          </div>

          <div className="mt-3 rounded-sm border border-warn/50 bg-warn-bg px-3 py-2 text-[13px]">
            <strong className="font-[560]">This console cannot change a price.</strong>
            <p className="mt-1 text-muted">{data.price_note}</p>
          </div>

          {hist && !hist.continuous ? (
            <Problem>
              The price history does not join up: a recorded change does not start where the
              previous one ended, or the last one does not end at today&apos;s price. Someone wrote
              the price outside the rail.
            </Problem>
          ) : null}
        </Card>
      ) : null}

      {data ? (
        <Card title="Who moved the price">
          {data.price_history_error ? <Problem>{data.price_history_error}</Problem> : null}
          {hist && hist.history.length === 0 ? (
            <Empty>No price change recorded. The pack still sells at the price it launched at.</Empty>
          ) : null}
          {hist && hist.history.length > 0 ? (
            <Scroll>
              <table className="w-full min-w-[520px] border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-border text-left text-[12px] uppercase tracking-[0.06em] text-subtle">
                    <th className="py-2 pr-3 font-[520]">when</th>
                    <th className="py-2 pr-3 font-[520]">from</th>
                    <th className="py-2 pr-3 font-[520]">to</th>
                    <th className="py-2 pr-3 font-[520]">who</th>
                    <th className="py-2 font-[520]">why</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {hist.history.map((h) => (
                    <tr key={h.id} className="border-b border-border align-top">
                      <td className="py-2 pr-3">
                        {clock(h.createdAt)}
                        <div className="text-[11px] text-subtle">{ago(h.createdAt)}</div>
                      </td>
                      <td className="py-2 pr-3">{money(h.fromPence)}</td>
                      <td className="py-2 pr-3">{money(h.toPence)}</td>
                      <td className="py-2 pr-3">{h.actor || ABSENT}</td>
                      <td className="wrap-any py-2 text-[11px] text-muted">{h.reason || ABSENT}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
          ) : null}
          {hist?.truncated ? <Note>Older changes exist and are not shown.</Note> : null}
        </Card>
      ) : null}

      {data && data.exists !== false ? (
        <Card title={data.listed ? 'Take it off the shelf' : 'Put it back on the shelf'}>
          <p className="text-[13px] text-muted">
            {data.listed
              ? 'The pack stops being buyable immediately. Buyers who already paid keep their download — an unlisting withdraws the offer, not the entitlement.'
              : 'The pack becomes buyable again. The API refuses this if the pack has no deliverable content key.'}
          </p>
          <label className="mt-3 block text-[12px] uppercase tracking-[0.06em] text-subtle">
            Why
          </label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="required — it is written to the audit log and the store"
            className="tap mt-1 w-full rounded-sm border border-border bg-surface px-3 text-[16px]"
          />
          <div className="mt-3">
            <Confirm
              action="catalogue.set_listing"
              kind={data.listed ? 'danger' : 'primary'}
              label={data.listed ? 'Unlist this pack' : 'Relist this pack'}
              disabled={!reason.trim()}
              payload={() => ({ id: data.id, listed: !data.listed, reason: reason.trim() })}
              onApplied={() => {
                setReason('');
                refresh();
              }}
              renderPreview={(p) => (
                <div className="text-[13px]">
                  <Row label="Pack">{String(p.title ?? data.id)}</Row>
                  <Row label="Now">{p.currently_listed ? 'on the shelf' : 'off the shelf'}</Row>
                  <Row label="After">{p.after ? 'on the shelf' : 'off the shelf'}</Row>
                  <Row label="Effect">{String(p.effect ?? '')}</Row>
                  <Row label="Endpoint">
                    <span className="wrap-any font-mono text-[11px]">{String(p.endpoint ?? '')}</span>
                  </Row>
                  <Row label="Touches the price">no</Row>
                  {p.no_change ? <Note>This changes nothing — it is already in that state.</Note> : null}
                  {p.warning ? <Problem>{String(p.warning)}</Problem> : null}
                  {p.currently_listed_basis ? (
                    <Note>{String(p.currently_listed_basis)}</Note>
                  ) : null}
                </div>
              )}
            />
          </div>
        </Card>
      ) : null}

      {pack ? (
        <Card title="What the buyer reads">
          <Row label="Headline">{(pack.headline as string) || ABSENT}</Row>
          <Row label="Subhead">{(pack.subhead as string) || ABSENT}</Row>
          <Row label="Proof point">{(pack.proofPoint as string) || ABSENT}</Row>
          <Row label="Who pays">{(pack.whoPays as string) || ABSENT}</Row>
          <Row label="Effort">{(pack.effortTag as string) || ABSENT}</Row>
          <Row label="Time to first revenue">{(pack.timeToFirstRevenue as string) || ABSENT}</Row>
          <Row label="Sources cited">{pack.sourceCount ?? ABSENT}</Row>
          <Row label="Verified">
            {pack.verifiedAt ? `${clock(String(pack.verifiedAt))} · ${ago(String(pack.verifiedAt))}` : ABSENT}
          </Row>
          <Row label="Dossier">
            <span className="wrap-any font-mono text-[11px]">
              {(pack.dossierRef as string) || ABSENT}
            </span>
          </Row>
          {pack.qaVerdictSummary ? (
            <p className="mt-2 text-[13px] text-muted">{String(pack.qaVerdictSummary)}</p>
          ) : null}
        </Card>
      ) : null}
    </Shell>
  );
}
