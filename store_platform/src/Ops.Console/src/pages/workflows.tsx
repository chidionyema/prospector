/**
 * Enforcements — the fences themselves, and whether they are still firing.
 *
 * Every other page on this console grades an OUTCOME: is the shelf clean, is the rail up, is the
 * engine running. The grades come from fences — CI, the deploy workflows, the live storefront
 * smoke, the weekly review, the escape-hatch drill. Nothing showed whether those fences were
 * still working, so the console could be green because everything passed, or green because
 * nothing had checked.
 *
 * Measured 2026-08-19, while the console showed no problem: the live storefront smoke had been
 * red for 30 hours, the escape-hatch drill had never completed a run, and `ci-autoscale.yml` had
 * failed at startup on all 19 of its runs. That last one is the shape of the whole problem — a
 * startup failure attaches to no pull request, so it turns nothing red anywhere.
 *
 * Three states worth separating, because only the first is visible without this page:
 *
 *   FAILING    last run was red.
 *   NEVER-RAN  no run at all. There is no red run to find, because there is no run.
 *   STOPPED    a scheduled workflow that has gone quiet. It does not fail; it stops firing.
 *
 * Read-only. This page reports; it does not rerun, restart or dispatch anything. The data is
 * `scripts/workflow_health.py`, the same module `scripts/process_audit.py` grades from, so the
 * console and the audit cannot disagree about which fences are up.
 */
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Scroll } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Grade = 'ok' | 'warn' | 'bad';

type WorkflowRow = {
  grade: Grade;
  file: string;
  path: string;
  name: string;
  detail: string;
  scheduled: string | null;
  conclusion: string | null;
  status: string | null;
  event: string | null;
  at: string | null;
  url: string | null;
  ever_ran: boolean | null;
};

type WorkflowsView = {
  generated_at: number;
  reachable: boolean;
  error?: string;
  note?: string;
  repo?: string;
  rows: WorkflowRow[];
  failing: number;
  warnings: number;
  ok: boolean;
  live_storefront: { grade: Grade; detail: string; url: string | null } | null;
};

const LABEL: Record<Grade, string> = { ok: 'ok', warn: 'warn', bad: 'FAILING' };

export default function Workflows() {
  const { data, envelope, error } = useOps<WorkflowsView>('workflows', {}, { pollMs: 300_000 });

  // Worst first. A page that lists eight healthy fences above the one that stopped has buried it.
  const order: Record<Grade, number> = { bad: 0, warn: 1, ok: 2 };
  const rows = data ? [...data.rows].sort((a, b) => order[a.grade] - order[b.grade]) : [];

  return (
    <Shell
      title="Workflows"
      intro="Every GitHub workflow this repo declares, and whether it is still firing. A fence that has stopped does not go red — it goes quiet, and quiet is what nothing else on this console can show."
    >
      {error && <Problem>{error}</Problem>}
      {!data && !error && <Note>asking GitHub about each workflow in turn</Note>}

      {data && !data.reachable && (
        <Card title="Could not ask GitHub" tone="warn">
          <Note>
            {data.error}. {data.note}
          </Note>
        </Card>
      )}

      {data && data.reachable && (
        <>
          <Card
            title="Verdict"
            tone={data.ok ? 'ok' : 'bad'}
            right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
          >
            {data.ok ? (
              <Note>Every declared workflow has run, and its last run was not red.</Note>
            ) : (
              <Note>
                {data.failing} failing, {data.warnings} warning(s) across {data.rows.length}{' '}
                workflows. Run <code>python3 scripts/workflow_health.py</code> for the same list in
                a terminal.
              </Note>
            )}
          </Card>

          {data.live_storefront && (
            <Card
              title="Live storefront"
              tone={data.live_storefront.grade}
              right={<Pill tone={data.live_storefront.grade}>{LABEL[data.live_storefront.grade]}</Pill>}
            >
              <Note>
                The storefront&apos;s own answer to &quot;is it broken right now&quot;:{' '}
                {data.live_storefront.detail}.{' '}
                {data.live_storefront.url && (
                  <a className="underline" href={data.live_storefront.url} target="_blank" rel="noreferrer">
                    open the run
                  </a>
                )}
              </Note>
            </Card>
          )}

          <Card
            title={`Workflows (${data.rows.length})`}
            tone={data.failing ? 'bad' : data.warnings ? 'warn' : 'ok'}
            right={
              data.failing ? <Pill tone="bad">{data.failing} failing</Pill> : <Pill tone="ok">clean</Pill>
            }
          >
            {rows.length === 0 ? (
              <Empty>this repo declares no workflows</Empty>
            ) : (
              <Scroll>
                <table className="w-full text-sm">
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.path} className="border-b border-border last:border-0 align-top">
                        <td className="py-2 pr-3 whitespace-nowrap">
                          <Pill tone={r.grade}>{LABEL[r.grade]}</Pill>
                        </td>
                        <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap">
                          {r.url ? (
                            <a className="underline" href={r.url} target="_blank" rel="noreferrer">
                              {r.file}
                            </a>
                          ) : (
                            r.file
                          )}
                          {r.scheduled && <span className="ml-2 text-subtle">{r.scheduled}</span>}
                        </td>
                        <td className="py-2 text-subtle">{r.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Scroll>
            )}
          </Card>
        </>
      )}
    </Shell>
  );
}
