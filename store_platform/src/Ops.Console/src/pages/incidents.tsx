/**
 * Incidents — what broke, and what stops it happening again.
 *
 * Why this page exists. Founder, 2026-08-18: "we need extreme visibility into what could go
 * wrong, also need incident report, as we are going to be doing this for incidents now." The
 * records were already readable from ops as raw JSON on the Docs page. Readable is not a report:
 * which incidents are still open, which have no mechanism behind them, and which have a mechanism
 * nobody has graded existed only in the terminal output of `scripts/incident.py check`.
 *
 * The judgement on this page is not written here. Every verdict comes from that same script, so
 * the page and the CI gate cannot drift into answering different questions about the same file.
 * See prospector/ops/incidents_view.py.
 *
 * The tier order is the point of the whole loop, so it is rendered rather than assumed: heal
 * beats refuse, refuse beats test, test beats memory. An estate whose incidents are all `memory`
 * has written a lot of notes and armed nothing.
 */
import { useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Spinner, Stat } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Incident = {
  id: string;
  title?: string;
  opened?: string;
  severity?: string;
  state: string;
  tier?: string | null;
  tier_means?: string;
  landed_on?: string | null;
  verdict: string;
  issue?: string | number | null;
  blocking: string[];
  overdue?: string | null;
  needs_ticket: boolean;
  doc?: string | null;
  what_broke?: string | null;
  mechanism?: string | null;
  class?: string | null;
  next: string;
  ok: boolean;
};

type Report = {
  generated_at: string;
  process: string;
  gate: string;
  note: string;
  tier_meaning: Record<string, string>;
  headline: {
    total: number;
    open: number;
    unguarded: number;
    unproven: number;
    overdue_grades: number;
    untracked: number;
    blocked: number;
    no_tier: number;
    by_tier: Record<string, number>;
  };
  incidents: Incident[];
};

/** Strongest first. The order is the rule, not a display preference. */
const TIER_ORDER = ['heal', 'refuse', 'test', 'memory'];

function stateTone(i: Incident): 'ok' | 'warn' | 'bad' | 'mute' {
  if (i.state === 'closed') return 'mute';
  if (i.state === 'malformed' || !i.landed_on) return 'bad';
  if (i.blocking.length || i.overdue) return 'warn';
  return 'ok';
}

function stateWord(i: Incident): string {
  if (i.state === 'malformed') return 'will not parse';
  if (i.state === 'closed') return 'closed';
  if (!i.landed_on) return 'nothing armed';
  if (i.blocking.length) return 'record incomplete';
  if (i.overdue) return 'grade overdue';
  if (i.verdict !== 'proven') return 'armed, ungraded';
  return 'proven';
}

export default function Incidents() {
  const [open, setOpen] = useState<string | null>(null);
  const report = useOps<Report>('incidents');
  const data = report.data;

  return (
    <Shell
      title="Incidents"
      intro="What broke, what stops it repeating, and what is still unguarded."
    >
      {report.error ? <Problem>{report.error}</Problem> : null}

      <Card
        title="Where the loop stands"
        right={<AsOf asOf={report.envelope?.as_of} tookMs={report.envelope?.took_ms} />}
      >
        {report.loading && !data ? <Spinner what="the incident records" /> : null}
        {data ? (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Records" value={data.headline.total} note="on disk" />
              <Stat label="Open" value={data.headline.open} tone={data.headline.open ? 'warn' : 'ok'} />
              <Stat
                label="Nothing armed"
                value={data.headline.unguarded}
                tone={data.headline.unguarded ? 'bad' : 'ok'}
                note="no mechanism has landed"
              />
              <Stat
                label="Ungraded"
                value={data.headline.unproven}
                tone={data.headline.unproven ? 'warn' : 'ok'}
                note="armed, never proven"
              />
              <Stat
                label="Overdue"
                value={data.headline.overdue_grades}
                tone={data.headline.overdue_grades ? 'bad' : 'ok'}
                note="window has closed"
              />
              <Stat
                label="Untracked"
                value={data.headline.untracked}
                tone={data.headline.untracked ? 'warn' : 'ok'}
                note="no issue open"
              />
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <span className="text-[12px] uppercase tracking-[0.06em] text-subtle">
                By mechanism
              </span>
              {TIER_ORDER.map((tier) => (
                <Pill key={tier} tone={data.headline.by_tier?.[tier] ? 'plain' : 'mute'}>
                  {tier} {data.headline.by_tier?.[tier] ?? 0}
                </Pill>
              ))}
              <Pill tone={data.headline.no_tier ? 'bad' : 'mute'}>
                no tier {data.headline.no_tier}
              </Pill>
              <span className="text-[12px] text-muted">
                Strongest first. Heal beats refuse, refuse beats test, test beats memory.
              </span>
            </div>
            <Note>
              {data.note} The gate is <span className="font-mono">{data.gate}</span>; the process
              is <span className="font-mono">{data.process}</span>.
            </Note>
          </>
        ) : null}
      </Card>

      <Card title="Every record, worst first">
        {report.loading && !data ? <Spinner what="the records" /> : null}
        {data && data.incidents.length === 0 ? (
          <Empty>No incident records under docs/incidents.</Empty>
        ) : null}

        <ul className="m-0 list-none p-0">
          {(data?.incidents ?? []).map((i) => (
            <li key={i.id} className="border-b border-border py-3 last:border-0">
              <div className="flex flex-wrap items-baseline gap-2">
                <button
                  type="button"
                  onClick={() => setOpen(i.id === open ? null : i.id)}
                  aria-expanded={i.id === open}
                  className="tap wrap-any text-left text-[14px] text-text underline-offset-2 hover:underline"
                >
                  {i.title ?? i.id}
                </button>
                <Pill tone={stateTone(i)}>{stateWord(i)}</Pill>
                {i.tier ? <Pill tone="mute">{i.tier}</Pill> : null}
                {i.severity ? <Pill tone="mute">{i.severity}</Pill> : null}
                {i.needs_ticket ? <Pill tone="warn">needs a ticket</Pill> : null}
              </div>
              <div className="mt-1 text-[13px] text-muted">{i.next}</div>

              {i.id === open ? (
                <div className="mt-3 border-l-2 border-border pl-3">
                  {i.what_broke ? (
                    <p className="mt-0 text-[13px] leading-[1.6] text-text">
                      <span className="text-subtle">What broke: </span>
                      {i.what_broke}
                    </p>
                  ) : null}
                  {i.class ? (
                    <p className="text-[13px] leading-[1.6] text-text">
                      <span className="text-subtle">The class: </span>
                      {i.class}
                    </p>
                  ) : null}
                  {i.mechanism ? (
                    <p className="text-[13px] leading-[1.6] text-text">
                      <span className="text-subtle">
                        What stops it{i.tier_means ? ` (${i.tier_means})` : ''}:{' '}
                      </span>
                      {i.mechanism}
                    </p>
                  ) : null}
                  {i.blocking.length ? (
                    <p className="text-[13px] leading-[1.6] text-text">
                      <span className="text-subtle">Stopping it closing: </span>
                      {i.blocking.join('; ')}
                    </p>
                  ) : null}
                  {i.overdue ? (
                    <p className="text-[13px] leading-[1.6] text-text">
                      <span className="text-subtle">Overdue: </span>
                      {i.overdue}
                    </p>
                  ) : null}
                  <p className="mb-0 font-mono text-[12px] text-subtle">
                    {i.id}
                    {i.opened ? ` · opened ${i.opened}` : ''}
                    {i.landed_on ? ` · armed ${i.landed_on}` : ''}
                    {` · grade ${i.verdict}`}
                    {i.issue ? ` · issue #${i.issue}` : ''}
                  </p>
                  {i.doc ? (
                    <p className="mb-0 mt-1 text-[13px]">
                      <a
                        className="underline underline-offset-2"
                        href={`/docs?open=${encodeURIComponent(i.doc)}`}
                      >
                        Read the full record
                      </a>
                    </p>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
    </Shell>
  );
}
