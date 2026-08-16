/**
 * Yield — what the filter is actually doing to the ideas that go in.
 *
 * Every rate on this page is computed in Python (`prospector/ops/metrics.py`) and rendered here
 * as-is. That is deliberate and it is the rule for the whole console: no engine metric is
 * derived in TypeScript. A second implementation of "pass rate" is a second answer to the same
 * question, and the two drift.
 *
 * Note the basis the engine states next to the rate: defers are EXCLUDED, because a defer is an
 * outage, not an outcome. Folding them in makes a bad afternoon on the retrieval chain look like
 * a stricter filter.
 */
import { useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Row, Scroll, Stat } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Metrics = {
  now: string;
  window_days: number | null;
  outcomes: {
    counts: Record<string, number>;
    ruled: number;
    pass_rate_pct: number | null;
    kill_rate_pct: number | null;
    rate_basis: string;
    rate_reason: string;
    defer: { n: number; share_of_catalogue_pct: number | null; note: string };
    provisional: { n: number; by_decision: Record<string, number>; note: string };
    reconciliation: { reconciled: boolean; deltas: Record<string, unknown>; reason: string };
  };
  gates: {
    kills: number;
    gates: { gate: string; n: number; pct: number | null }[];
    unrecorded: number;
    unrecorded_note: string;
    reason: string;
  };
  rates: {
    points: { day: string; pass_rate_pct: number | null; vetted: number; outage_rate_pct: number | null }[];
    totals: {
      batches: number;
      pass: number;
      kill: number;
      defer: number;
      vetted: number;
      ruled: number;
      pass_rate_pct: number | null;
      kill_rate_pct: number | null;
      outage_rate_pct: number | null;
    };
    records: number;
    reason: string;
  };
  verdicts: {
    rows: { check: string; n: number; unverifiable_pct: number | null; supported_pct: number | null }[];
    observations: number;
    retrieval_failed_checks: number;
    retrieval_failed_note: string;
    reason: string;
  };
  funnel: {
    steps: { stage: string; n: number }[];
    dropped_total: number;
    outage_total: number;
    unfinished_total: number;
    kill_gates: Record<string, number>;
  };
};

export default function MetricsPage() {
  const [days, setDays] = useState<number | ''>('');
  const { data, envelope, error } = useOps<Metrics>('metrics', days ? { window_days: days } : {});

  return (
    <Shell title="Yield" intro="What the filter does to the ideas that go into it.">
      {error ? <Problem>{error}</Problem> : null}

      <Card
        title="Window"
        right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
      >
        <div className="flex flex-wrap gap-2">
          {([['', 'all time'], [7, '7d'], [30, '30d'], [90, '90d']] as [number | '', string][]).map(
            ([v, label]) => (
              <button
                key={label}
                onClick={() => setDays(v)}
                className={`tap rounded-sm border px-3 text-[13px] ${
                  v === days
                    ? 'border-action bg-action text-on-action'
                    : 'border-border bg-surface text-muted'
                }`}
              >
                {label}
              </button>
            ),
          )}
        </div>
      </Card>

      {!data ? <Card>reading the catalogue…</Card> : null}

      {data ? (
        <Card title="Verdicts">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="pass" value={data.outcomes.counts.pass} tone="ok" />
            <Stat label="kill" value={data.outcomes.counts.kill} tone="bad" />
            <Stat
              label="pass rate"
              value={data.outcomes.pass_rate_pct === null ? null : `${data.outcomes.pass_rate_pct}%`}
            />
            <Stat
              label="waiting (defer)"
              value={data.outcomes.defer.n}
              tone={data.outcomes.defer.n ? 'warn' : 'plain'}
            />
          </div>
          <div className="mt-3 text-[12px] text-muted">Basis: {data.outcomes.rate_basis}</div>
          {data.outcomes.rate_reason ? (
            <div className="mt-1 text-[12px] text-warn-strong">{data.outcomes.rate_reason}</div>
          ) : null}
          <div className="mt-2">
            <Note>{data.outcomes.defer.note}</Note>
          </div>
          {data.outcomes.provisional.n > 0 ? (
            <div className="mt-2">
              <Note>
                {data.outcomes.provisional.n} provisional row(s). {data.outcomes.provisional.note}
              </Note>
            </div>
          ) : null}
          {!data.outcomes.reconciliation.reconciled ? (
            <div className="mt-2">
              <Problem>
                Two counts of the same catalogue disagree: {data.outcomes.reconciliation.reason}
              </Problem>
            </div>
          ) : null}
        </Card>
      ) : null}

      {data ? (
        <Card title="What kills them">
          {data.gates.gates.length === 0 ? (
            <Empty>{data.gates.reason || 'no kill recorded'}</Empty>
          ) : (
            <div className="flex flex-col gap-2">
              {data.gates.gates.map((g) => (
                <div key={g.gate}>
                  <div className="flex items-baseline justify-between gap-3 text-[13px]">
                    <span className="font-mono">{g.gate}</span>
                    <span className="font-mono text-subtle">
                      {g.n}
                      {g.pct === null ? '' : ` · ${g.pct}%`}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 w-full rounded-sm bg-surface3">
                    <div
                      className="h-1.5 rounded-sm bg-bad"
                      style={{ width: `${Math.min(100, g.pct ?? 0)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
          {data.gates.unrecorded > 0 ? <Note>{data.gates.unrecorded_note}</Note> : null}
        </Card>
      ) : null}

      {data ? (
        <Card title="The funnel">
          <div className="flex flex-col gap-1">
            {data.funnel.steps.map((s) => (
              <Row key={s.stage} label={s.stage}>
                {s.n}
              </Row>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Pill tone="bad">{data.funnel.dropped_total} dropped</Pill>
            <Pill tone="warn">{data.funnel.outage_total} lost to outages</Pill>
            <Pill tone="mute">{data.funnel.unfinished_total} unfinished</Pill>
          </div>
        </Card>
      ) : null}

      {data ? (
        <Card title="Checks, and how often they can be answered">
          <Scroll>
            <table className="w-full min-w-[420px] border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-border text-left text-[12px] uppercase tracking-[0.06em] text-subtle">
                  <th className="py-2 pr-3 font-[520]">check</th>
                  <th className="py-2 pr-3 font-[520]">seen</th>
                  <th className="py-2 pr-3 font-[520]">supported</th>
                  <th className="py-2 font-[520]">unverifiable</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {data.verdicts.rows.map((r) => (
                  <tr key={r.check} className="border-b border-border">
                    <td className="py-2 pr-3">{r.check}</td>
                    <td className="py-2 pr-3">{r.n}</td>
                    <td className="py-2 pr-3">
                      {r.supported_pct === null ? '—' : `${r.supported_pct}%`}
                    </td>
                    <td className="py-2">
                      {r.unverifiable_pct === null ? '—' : `${r.unverifiable_pct}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <div className="mt-2">
            <Note>{data.verdicts.retrieval_failed_note}</Note>
          </div>
        </Card>
      ) : null}

      {data && data.rates.points.length ? (
        <Card title="Day by day">
          <Scroll>
            <table className="w-full min-w-[420px] border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-border text-left text-[12px] uppercase tracking-[0.06em] text-subtle">
                  <th className="py-2 pr-3 font-[520]">day</th>
                  <th className="py-2 pr-3 font-[520]">vetted</th>
                  <th className="py-2 pr-3 font-[520]">pass rate</th>
                  <th className="py-2 font-[520]">outage rate</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {data.rates.points
                  .slice()
                  .reverse()
                  .map((p) => (
                    <tr key={p.day} className="border-b border-border">
                      <td className="py-2 pr-3">{p.day}</td>
                      <td className="py-2 pr-3">{p.vetted}</td>
                      <td className="py-2 pr-3">
                        {p.pass_rate_pct === null ? '—' : `${p.pass_rate_pct}%`}
                      </td>
                      <td className="py-2">
                        {p.outage_rate_pct === null ? '—' : `${p.outage_rate_pct}%`}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </Scroll>
        </Card>
      ) : null}
    </Shell>
  );
}
