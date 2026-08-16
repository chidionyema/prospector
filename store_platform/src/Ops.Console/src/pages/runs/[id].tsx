/**
 * One run: the ideas it touched, in the order it touched them.
 *
 * A candidate the run STARTED but never finished is shown, with its reason, rather than dropped.
 * That row is the most interesting one in a run that died mid-batch, and a view that silently
 * omits it reports a clean run.
 */
import { useRouter } from 'next/router';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Row } from '@/components/ui';
import { ABSENT, clock, duration, runTimes } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Candidate = {
  candidate_id: string;
  title: string | null;
  tier: string | null;
  full_vet: boolean | null;
  started_at: string | null;
  done_at: string | null;
  decision: string | null;
  decision_null_reason?: string;
  gate: string | null;
  provisional: boolean | null;
  checks_seen: number;
  outage_checks: number;
  soft_early_exit: { after_check?: string; gate?: string; skipped?: number } | null;
  dossier: { status: string; reason: string; path: string | null; decision?: string; gate_fired?: string };
};
type RunView = {
  run_id: string;
  found: boolean;
  not_found_reason: string;
  pid: number | null;
  first_ts: string | null;
  last_ts: string | null;
  events: number;
  candidates: Candidate[];
  retrieval: {
    distinct_queries: number;
    latency_ms: number | null;
    latency_null_reason: string;
    errors: number;
  };
  cost_usd: number | null;
  cost_null_reason: string;
  unreadable_lines: number;
};

export default function RunDetail() {
  const router = useRouter();
  const runId = typeof router.query.id === 'string' ? router.query.id : '';
  const { data, envelope, error } = useOps<RunView>(runId ? 'run' : null, { run_id: runId, days: 14 });
  const t = runTimes(data?.first_ts, data?.last_ts);

  return (
    <Shell title="Run" intro={runId}>
      {error ? <Problem>{error}</Problem> : null}
      {data && !data.found ? (
        <Card>
          <Note>{data.not_found_reason}</Note>
        </Card>
      ) : null}

      {data?.found ? (
        <Card title="Timing" right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}>
          <Row label="Started">{t.started}</Row>
          <Row label="Ended">{t.ended}</Row>
          <Row label="Took">{t.took}</Row>
          <Row label="That was">{t.ago}</Row>
          <Row label="Process id">{data.pid ?? ABSENT}</Row>
          <Row label="Audit events">{data.events}</Row>
          <Row label="Searches">
            {data.retrieval.distinct_queries} distinct
            {data.retrieval.latency_ms === null
              ? ` · ${data.retrieval.latency_null_reason}`
              : ` · ${duration(data.retrieval.latency_ms / 1000)} of retrieval`}
            {data.retrieval.errors ? ` · ${data.retrieval.errors} errors` : ''}
          </Row>
          <Row label="Cost">{data.cost_null_reason}</Row>
        </Card>
      ) : null}

      {data?.found ? (
        <Card title={`${data.candidates.length} idea(s)`}>
          {data.candidates.length === 0 ? <Empty>This run logged no candidate.</Empty> : null}
          <div className="flex flex-col gap-3">
            {data.candidates.map((c) => (
              <CandidateCard key={c.candidate_id} c={c} />
            ))}
          </div>
        </Card>
      ) : null}
    </Shell>
  );
}

function CandidateCard({ c }: { c: Candidate }) {
  const t = runTimes(c.started_at, c.done_at);
  const decided = c.decision !== null;
  const tone =
    c.decision === 'pass' ? 'ok' : c.decision === 'kill' ? 'bad' : decided ? 'warn' : 'mute';
  return (
    <div className="rounded-sm border border-border px-3 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[14px] font-[520]">{c.title || 'untitled'}</span>
        <Pill tone={tone}>{c.decision ?? 'unfinished'}</Pill>
      </div>
      <div className="wrap-any font-mono text-[11px] text-subtle">{c.candidate_id}</div>

      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] sm:grid-cols-4">
        <TimeCell label="started" value={t.started} />
        <TimeCell label="ended" value={c.done_at ? clock(c.done_at) : 'never'} />
        <TimeCell label="took" value={t.took} />
        <TimeCell label="that was" value={t.ago} />
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5 text-[12px]">
        {c.tier ? <Pill tone="mute">{c.tier}</Pill> : null}
        {c.provisional ? <Pill tone="warn">provisional</Pill> : null}
        {c.gate ? <Pill tone="bad">gate: {c.gate}</Pill> : null}
        <Pill tone="mute">{c.checks_seen} checks</Pill>
        {c.outage_checks ? <Pill tone="warn">{c.outage_checks} hit an outage</Pill> : null}
        {c.soft_early_exit ? (
          <Pill tone="mute">
            stopped early after {c.soft_early_exit.after_check ?? '?'}
          </Pill>
        ) : null}
      </div>

      {c.decision_null_reason ? (
        <div className="mt-2 text-[12px] text-warn-strong">{c.decision_null_reason}</div>
      ) : null}
      {c.dossier.status !== 'ok' ? (
        <div className="mt-1 text-[12px] text-muted">dossier: {c.dossier.reason}</div>
      ) : null}
    </div>
  );
}

function TimeCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.06em] text-subtle">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}
