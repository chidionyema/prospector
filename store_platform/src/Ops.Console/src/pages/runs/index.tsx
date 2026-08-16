/**
 * Runs — what the engine did, when, and how long it took.
 *
 * Founder requirement, verbatim: "engine runs must show when a run started, when it ended, how
 * long it took, and how long ago that was. A run row with no time on it is not acceptable."
 * `runTimes()` produces exactly those four, and produces the words "not recorded" when a
 * timestamp is missing rather than a zero.
 *
 * The primary view on a phone is a stack of cards, not a table. The founder rejected dense
 * tables as the mobile view, and a run has six facts, which is three columns too many for a
 * 390px screen.
 */
import Link from 'next/link';
import { useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem } from '@/components/ui';
import { runTimes } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type RunRow = {
  run_id: string;
  pid: number | null;
  first_ts: string | null;
  last_ts: string | null;
  events: number;
  candidates: number;
  decisions: Record<string, number>;
  checks: number;
  outage_checks: number;
  searches: number;
  search_errors: number;
  cost_usd: number | null;
  cost_null_reason: string;
};
type RunsView = {
  runs: RunRow[];
  window_days: number;
  dir: string;
  files: string[];
  unreadable_lines: number;
  note: string;
};

export default function Runs() {
  const [days, setDays] = useState(3);
  const { data, envelope, error, loading } = useOps<RunsView>('runs', { days });

  return (
    <Shell title="Runs" intro="Every batch the engine ran, newest first.">
      {error ? <Problem>{error}</Problem> : null}

      <Card
        title={`Last ${days} day${days === 1 ? '' : 's'}`}
        right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
      >
        <div className="flex flex-wrap gap-2">
          {[1, 3, 7, 14].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`tap rounded-sm border px-3 text-[13px] ${
                d === days
                  ? 'border-action bg-action text-on-action'
                  : 'border-border bg-surface text-muted'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
        {data?.note ? <div className="mt-3"><Note>{data.note}</Note></div> : null}
        {data && data.unreadable_lines > 0 ? (
          <div className="mt-2">
            <Note>
              {data.unreadable_lines} audit line(s) could not be parsed and are NOT counted below.
            </Note>
          </div>
        ) : null}
      </Card>

      {loading && !data ? <Card>reading the audit log…</Card> : null}

      {data && data.runs.length === 0 ? (
        <Card>
          <Empty>No run in this window.</Empty>
        </Card>
      ) : null}

      {(data?.runs ?? []).map((r) => (
        <RunCard key={r.run_id} r={r} />
      ))}
    </Shell>
  );
}

function RunCard({ r }: { r: RunRow }) {
  const t = runTimes(r.first_ts, r.last_ts);
  const decisions = Object.entries(r.decisions ?? {});
  return (
    <Link
      href={`/runs/${encodeURIComponent(r.run_id)}`}
      className="block rounded-sm border border-border bg-surface px-4 py-3 hover:bg-surface2"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="wrap-any font-mono text-[13px] font-[520]">{r.run_id}</span>
        {t.running ? <Pill tone="ok">running</Pill> : null}
      </div>

      {/* The four time facts, always, in this order. */}
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px] sm:grid-cols-4">
        <div>
          <dt className="text-[11px] uppercase tracking-[0.06em] text-subtle">started</dt>
          <dd className="font-mono">{t.started}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-[0.06em] text-subtle">ended</dt>
          <dd className="font-mono">{t.ended}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-[0.06em] text-subtle">took</dt>
          <dd className="font-mono">{t.took}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-[0.06em] text-subtle">that was</dt>
          <dd className="font-mono">{t.ago}</dd>
        </div>
      </dl>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
        <Pill tone="mute">{r.candidates} ideas</Pill>
        {decisions.map(([k, v]) => (
          <Pill key={k} tone={k === 'pass' ? 'ok' : k === 'kill' ? 'bad' : 'warn'}>
            {k} {v}
          </Pill>
        ))}
        {r.outage_checks > 0 ? (
          <Pill tone="warn">{r.outage_checks} checks hit an outage</Pill>
        ) : null}
        {r.search_errors > 0 ? <Pill tone="warn">{r.search_errors} search errors</Pill> : null}
      </div>

      <div className="mt-1 text-[11px] text-subtle">
        cost not attributed here — {r.cost_null_reason}
      </div>
    </Link>
  );
}
