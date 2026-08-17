/**
 * Stranded — every pack the engine passed that a buyer cannot buy, and the button that fixes it.
 *
 * This is the revenue gap stated as a number. A pack that cleared every gate and is not on the
 * shelf earned nothing, and until 2026-08-16 the only way to see the list was to run
 * `tools/verify_pass_shelf_coverage.py` at a terminal — which is exactly the kind of thing the
 * founder said an admin console exists to remove.
 *
 * The repairs are the tools that already exist. The console does not reimplement them; it makes
 * them reachable, and records a receipt for each run.
 */
import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Mono, Note, Pill, Problem, Row, Scroll, Spinner, Stat } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type ShelfRow = {
  id: string;
  created: string;
  why: string;
  checks: string[];
  repair: string;
  verdict: string;
};

type ShelfView = {
  reachable: boolean;
  reason?: string;
  shelf_packs: number | null;
  stranded: number | null;
  stale_verdicts?: number;
  rows: ShelfRow[];
  by_reason?: Record<string, number>;
  by_repair?: Record<string, number>;
  note?: string;
};

const REPAIR_LABEL: Record<string, string> = {
  'shelf.repair_copy': 'rewrite the copy',
  'shelf.publish_pending': 'publish it',
  'shelf.regate': 're-ask the gate',
  manual: 'needs a person',
};

export default function StrandedShelf() {
  const { data, envelope, error, refresh } = useOps<ShelfView>('shelf', {}, { pollMs: 120_000 });

  const rows = data?.rows ?? [];
  const byRepair = data?.by_repair ?? {};
  const copyCount = byRepair['shelf.repair_copy'] ?? 0;
  const publishCount = byRepair['shelf.publish_pending'] ?? 0;
  const regateCount = byRepair['shelf.regate'] ?? 0;
  const manualCount = byRepair['manual'] ?? 0;

  return (
    <Shell
      title="Stranded"
      intro="Packs the engine passed that nobody can buy yet. Each one is finished work earning nothing."
    >
      {error ? <Problem>{error}</Problem> : null}
      {!data ? <Spinner what="counting the shelf" /> : null}

      {data && !data.reachable ? (
        <Card title="The shelf could not be read">
          <Note>{data.reason}</Note>
          <Note>
            That is UNKNOWN, not zero. This page will not tell you nothing is stranded because the
            network failed.
          </Note>
        </Card>
      ) : null}

      {data?.reachable ? (
        <Card
          title="The gap"
          right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
        >
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            <Stat label="on the shelf" value={data.shelf_packs ?? 0} note="a buyer can buy these" tone="ok" />
            <Stat
              label="stranded"
              value={data.stranded ?? 0}
              note="passed, unbuyable"
              tone={(data.stranded ?? 0) > 0 ? 'bad' : 'ok'}
            />
            <Stat
              label="stale verdicts"
              value={data.stale_verdicts ?? 0}
              note="gated by older rules"
              tone={(data.stale_verdicts ?? 0) > 0 ? 'warn' : 'ok'}
            />
            <Stat label="copy to rewrite" value={copyCount} note="one button" />
            <Stat label="never published" value={publishCount} note="one button" />
          </div>
          {manualCount ? (
            <Note>
              {manualCount} of them need a person: no tool repairs that class today.
            </Note>
          ) : null}
        </Card>
      ) : null}

      {data?.reachable && (data.stranded ?? 0) > 0 ? (
        <Card title="Fix them">
          <div className="flex flex-col gap-5">
            <div>
              <Row label={`Rewrite the shelf copy (${copyCount})`}>
                the linter rejected the one-liner a buyer reads
              </Row>
              <div className="mt-2">
                <Confirm
                  action="shelf.repair_copy"
                  kind="primary"
                  label={`Rewrite copy on ${copyCount} pack${copyCount === 1 ? '' : 's'}`}
                  disabled={copyCount === 0}
                  payload={() => ({ actor: 'console', reason: 'unblock the stranded shelf' })}
                  renderPreview={(p) => (
                    <div className="flex flex-col gap-1">
                      <div>{String(p.effect ?? '')}</div>
                      <Mono>{String(p.command ?? '')}</Mono>
                      <Note>{String(p.note ?? '')}</Note>
                    </div>
                  )}
                  onApplied={refresh}
                />
              </div>
            </div>

            <div>
              <Row label={`Publish what was never published (${publishCount})`}>
                these cleared every gate and were never sent to the shelf
              </Row>
              <div className="mt-2">
                <Confirm
                  action="shelf.publish_pending"
                  kind="primary"
                  label={`Publish ${publishCount} pack${publishCount === 1 ? '' : 's'}`}
                  disabled={publishCount === 0}
                  payload={() => ({ actor: 'console', reason: 'unblock the stranded shelf' })}
                  renderPreview={(p) => (
                    <div className="flex flex-col gap-1">
                      <div>{String(p.effect ?? '')}</div>
                      <Mono>{String(p.command ?? '')}</Mono>
                      <Note>{String(p.note ?? '')}</Note>
                    </div>
                  )}
                  onApplied={refresh}
                />
              </div>
            </div>
            <div>
              <Row label={`Re-ask the gate (${regateCount})`}>
                these were judged by linter rules that have since changed, so the stored verdict
                is not an answer about today&apos;s rules
              </Row>
              <div className="mt-2">
                <Confirm
                  action="shelf.regate"
                  kind="primary"
                  label={`Re-gate ${regateCount} pack${regateCount === 1 ? '' : 's'}`}
                  disabled={regateCount === 0}
                  payload={() => ({ actor: 'console', reason: 'the linter rules moved' })}
                  renderPreview={(p) => (
                    <div className="flex flex-col gap-1">
                      <div>{String(p.effect ?? '')}</div>
                      <Mono>{String(p.command ?? '')}</Mono>
                      <Note>{String(p.note ?? '')}</Note>
                    </div>
                  )}
                  onApplied={refresh}
                />
              </div>
            </div>
          </div>
          <Note>
            None of these touches price or payment. They unblock packs the engine already
            passed, at the price the catalogue already holds. Re-gating is a rehearsal: it
            refreshes the verdict on disk, mints no Stripe object and puts nothing on sale.
          </Note>
        </Card>
      ) : null}

      {data?.reachable && data.by_reason && Object.keys(data.by_reason).length ? (
        <Card title="What is blocking them">
          <Scroll>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(data.by_reason).map(([k, v]) => (
                <Pill key={k} tone="bad">
                  {k} {v}
                </Pill>
              ))}
            </div>
          </Scroll>
        </Card>
      ) : null}

      {data?.reachable ? (
        <Card title={`Every stranded pack (${rows.length})`}>
          {rows.length === 0 ? (
            <Empty>Nothing is stranded. Every pass the engine produced is on the shelf.</Empty>
          ) : (
            <div className="flex flex-col gap-3">
              {rows.map((r) => (
                <div key={r.id} className="border-b border-hair pb-3 last:border-0 last:pb-0">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <Mono>{r.id}</Mono>
                    <span className="text-[11px] text-subtle">{r.created}</span>
                    <Pill tone={r.repair === 'manual' ? 'mute' : 'ok'}>
                      {REPAIR_LABEL[r.repair] ?? r.repair}
                    </Pill>
                    {r.verdict && r.verdict !== 'current' ? (
                      <Pill tone="warn">{r.verdict}</Pill>
                    ) : null}
                  </div>
                  <div className="mt-1 text-[13px] text-muted">{r.why}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      ) : null}

      {data?.note ? <Note>{data.note}</Note> : null}
    </Shell>
  );
}
