/**
 * Now — "is it running, and is it healthy", answerable in one glance without scrolling.
 *
 * Founder requirement, verbatim: "real information hierarchy: is it running and is it healthy
 * readable in one glance without scrolling." So the first card is a single verdict sentence and
 * nothing else, and everything under it is the evidence for that sentence, in the order an
 * operator would ask.
 *
 * Every number here comes from `read status`. Nothing on this page is computed in TypeScript —
 * not a rate, not a percentage, not a health verdict. The one thing the browser derives is which
 * of the engine's own flags is the WORST, which is a presentation choice, not a measurement.
 */
import Link from 'next/link';

import Shell from '@/components/Shell';
import { AsOf, Card, Note, Pill, Problem, Row, Stat } from '@/components/ui';
import { ABSENT, ago, duration } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Heartbeat = {
  role: string;
  present: boolean;
  age_s: number | null;
  stale: boolean;
  alive: boolean;
  why: string;
};
type PauseScope = {
  scope: string;
  armed: boolean;
  armed_at: string | null;
  actor: string | null;
  reason: string | null;
  stops: string;
  keeps_running: string;
};
type Tier = {
  name: string;
  state: string;
  trusted_final: boolean;
  dead_for_s: number | null;
  last_error: string | null;
  roles: { role: string; position: number }[];
};
type StuckItem = {
  candidate_id: string;
  run_id: string;
  title: string;
  tier: string;
  state: string;
  reason: string;
  pid: number | null;
  age_s: number | null;
  started_at: string | null;
};
type Stuck = {
  needs_attention: number | null;
  needs_attention_null_reason?: string;
  in_flight?: number;
  counts?: Record<string, number>;
  items?: StuckItem[];
  shown?: number;
  window_days?: number;
  stall_after_min?: number;
  awaiting_recovery?: {
    count: number | null;
    count_null_reason?: string;
    in_progress?: number;
    unreadable?: number;
    note?: string;
  };
  error?: string;
};
type Status = {
  heartbeats: { producer: Heartbeat; consumer: Heartbeat };
  alerts: { active: unknown[]; count: number; banner: string | null; note: string | null };
  stuck: Stuck;
  pause: { scopes: PauseScope[]; any_armed: boolean };
  providers: { tiers: Tier[]; moat_blind: string; drain_blind: string; trusted_final: string[] };
  queue: {
    backlog: {
      workable: number;
      orphaned: number;
      stalled: number;
      unpublishable: number;
      oldest_created_at: string | null;
    };
    leases: { held: number; expired: number; total: number };
    drain: { resumed: number; rate_per_h: number | null; eta_h: number | null; eta_reason: string };
  };
  routing: {
    head: string;
    head_trusted: boolean;
    publishes: boolean;
    problems: string[];
    advisories: string[];
    moat_primary_declared: string[];
  };
  spend: {
    today_usd: number | null;
    cap_usd: number | null;
    cap_armed: boolean;
    warnings: string[];
    day: string;
  };
};

export default function Now() {
  // 30s. Slow enough that the laptop is not spawning Python continuously, fast enough that a
  // pause taken from a phone is visible before the operator wonders whether it worked.
  const { data, envelope, error, loading, refresh } = useOps<Status>('status', {}, { pollMs: 30_000 });

  return (
    <Shell title="Now" intro="Whether the engine is running, and whether anything is wrong.">
      {error ? <Problem>{error}</Problem> : null}
      {loading && !data ? <Card>reading the engine…</Card> : null}
      {data ? <Verdict s={data} /> : null}
      {data ? <StuckWork stuck={data.stuck} /> : null}

      {data ? (
        <Card
          title="Roles"
          right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
        >
          <RoleRow hb={data.heartbeats.producer} what="Producer — invents ideas" />
          <RoleRow hb={data.heartbeats.consumer} what="Consumer — checks and rules them" />
        </Card>
      ) : null}

      {data ? (
        <Card title="Waiting work" right={<Link className="underline" href="/queue">queue</Link>}>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat
              label="workable"
              value={data.queue.backlog.workable}
              note="rows the drain can actually move"
            />
            <Stat label="stalled" value={data.queue.backlog.stalled} tone={data.queue.backlog.stalled ? 'warn' : 'plain'} />
            <Stat label="orphaned" value={data.queue.backlog.orphaned} tone={data.queue.backlog.orphaned ? 'warn' : 'plain'} />
            <Stat label="leases held" value={data.queue.leases.held} note={`${data.queue.leases.expired} expired`} />
          </div>
          <div className="mt-3 text-[13px] text-muted">
            Oldest waiting item: <span className="font-mono">{ago(data.queue.backlog.oldest_created_at)}</span>
          </div>
          <div className="text-[13px] text-muted">
            Drain: {data.queue.drain.rate_per_h === null ? (
              <span className="font-mono">{data.queue.drain.eta_reason || ABSENT}</span>
            ) : (
              <span className="font-mono">
                {data.queue.drain.rate_per_h}/h
                {data.queue.drain.eta_h !== null ? ` · empty in ${duration(data.queue.drain.eta_h * 3600)}` : ''}
              </span>
            )}
          </div>
        </Card>
      ) : null}

      {/* "Money today" until 2026-08-17, when a Money group arrived that is about the payment
          rail. Two things called money, one of them costs and the other takes, is how a glance at
          a dashboard produces the wrong conclusion. This card is what the engine SPENDS. */}
      {data ? (
        <Card title="What the engine cost today" right={<Link className="underline" href="/spend">spend</Link>}>
          <div className="grid grid-cols-2 gap-4">
            <Stat
              label="billed today"
              value={data.spend.today_usd === null ? null : `$${data.spend.today_usd.toFixed(2)}`}
              note={data.spend.day}
            />
            <Stat
              label="daily cap"
              value={data.spend.cap_armed && data.spend.cap_usd ? `$${data.spend.cap_usd.toFixed(2)}` : null}
              note={data.spend.cap_armed ? 'armed' : 'no cap armed'}
              tone={data.spend.cap_armed ? 'plain' : 'warn'}
            />
          </div>
          {data.spend.warnings?.length ? (
            <div className="mt-3 flex flex-col gap-2">
              {data.spend.warnings.map((w) => (
                <Note key={w}>{w}</Note>
              ))}
            </div>
          ) : null}
        </Card>
      ) : null}

      {data ? (
        <Card title="Brains" right={<Link className="underline" href="/engine">engine</Link>}>
          <Row label="Head of the verdict chain">
            <Pill tone={data.routing.head_trusted ? 'ok' : 'warn'}>{data.routing.head}</Pill>{' '}
            {data.routing.head_trusted ? 'rules finally' : 'provisional — will not publish'}
          </Row>
          <Row label="Trusted to rule finally">{data.routing.moat_primary_declared.join(', ')}</Row>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {data.providers.tiers.map((t) => (
              <Pill key={t.name} tone={t.state === 'live' ? 'ok' : t.state === 'dead' ? 'bad' : 'warn'}>
                {t.name}
                <span className="text-[11px] opacity-70">
                  {t.state === 'live' ? 'live' : `${t.state}${t.dead_for_s ? ` ${duration(t.dead_for_s)}` : ''}`}
                </span>
              </Pill>
            ))}
          </div>
          {data.routing.problems?.length ? (
            <div className="mt-3 flex flex-col gap-2">
              {data.routing.problems.map((p) => (
                <Problem key={p}>{p}</Problem>
              ))}
            </div>
          ) : null}
          {data.routing.advisories?.length ? (
            <div className="mt-2 flex flex-col gap-2">
              {data.routing.advisories.map((a) => (
                <Note key={a}>{a}</Note>
              ))}
            </div>
          ) : null}
        </Card>
      ) : null}

      <Card title="Reading">
        <Row label="Last read">
          <AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />
        </Row>
        <Row label="Refresh">
          <button className="underline" onClick={refresh}>
            read again now
          </button>
        </Row>
        <Row label="Poll">every 30s while this tab is open</Row>
      </Card>
    </Shell>
  );
}

/**
 * Work that started and never got a verdict, on the front page.
 *
 * This used to be visible only by opening a run and reading one candidate's detail, so a batch
 * that died left no mark anywhere an operator looks. The engine cannot report its own death: a
 * killed process never writes `candidate_done` (`run.py:1063`), so the ONLY evidence is a row
 * that is missing, and a missing row draws nothing.
 *
 * Work still being vetted is not shown as a fault. It is counted separately and said plainly,
 * because a card that cries about healthy work is a card the operator learns to skip.
 */
function StuckWork({ stuck }: { stuck: Stuck }) {
  if (stuck.error) {
    return (
      <Card title="Work that stopped">
        <Problem>{stuck.error}</Problem>
        <Note>{stuck.needs_attention_null_reason}</Note>
      </Card>
    );
  }
  const bad = stuck.needs_attention ?? 0;
  const items = stuck.items ?? [];
  // The audit log is a HISTORY: it still names work that died four days ago after the engine has
  // already re-vetted it. The in-flight ledger is the LIVE answer, so this is the number that
  // actually falls to zero — and the one that says whether a human has to do anything.
  const queued = stuck.awaiting_recovery?.count ?? null;
  return (
    <Card
      title="Work that stopped"
      right={<Link className="underline" href="/runs">runs</Link>}
    >
      <div className="grid grid-cols-3 gap-4">
        <Stat
          label="never finished"
          value={bad}
          tone={bad ? 'bad' : 'plain'}
          note={`started, no verdict, in the last ${stuck.window_days ?? 3} days`}
        />
        <Stat
          label="queued for repair"
          value={queued === null ? '—' : queued}
          tone={queued ? 'warn' : 'plain'}
          note={
            queued === null
              ? stuck.awaiting_recovery?.count_null_reason ?? 'not measured'
              : 're-vetted automatically at the start of every drain — nothing to do'
          }
        />
        <Stat
          label="being vetted now"
          value={stuck.in_flight ?? 0}
          note="live process, working — not a fault"
        />
      </div>
      {bad === 0 ? (
        <Note>Every candidate that started in the window has a verdict or is still running.</Note>
      ) : (
        <>
          <div className="mt-3 space-y-2">
            {items.map((it) => (
              <div key={`${it.run_id}:${it.candidate_id}`} className="text-[13px]">
                <Link className="underline" href={`/runs/${it.run_id}`}>
                  {it.title || it.candidate_id}
                </Link>{' '}
                <Pill tone="bad">{it.state}</Pill>{' '}
                <span className="text-muted">
                  {it.tier ? `${it.tier} · ` : ''}started {ago(it.started_at)}
                  {it.pid === null ? '' : ` · pid ${it.pid}`}
                </span>
                <div className="text-muted">{it.reason}</div>
              </div>
            ))}
          </div>
          {bad > (stuck.shown ?? 0) ? (
            <Note>
              Showing {stuck.shown} of {bad}. The count above is the full number, not the list
              length.
            </Note>
          ) : null}
        </>
      )}
    </Card>
  );
}

/**
 * The one-sentence answer, at the top, in the largest type on the page.
 *
 * The order of the tests is the order of severity, and each is a flag the ENGINE set. A paused
 * engine is not "unhealthy" — it is stopped on purpose, and saying "DOWN" for it would train the
 * operator to ignore the word.
 */
function Verdict({ s }: { s: Status }) {
  const paused = s.pause.scopes.filter((p) => p.armed);
  const alerts = s.alerts.count > 0;
  const blind = Boolean(s.providers.moat_blind);
  const stuck = s.stuck?.needs_attention ?? 0;
  const producer = s.heartbeats.producer.alive;
  const consumer = s.heartbeats.consumer.alive;

  let tone: 'ok' | 'warn' | 'bad' = 'ok';
  let headline = 'Running.';
  let detail = 'Both roles are beating and no alert is raised.';

  if (blind) {
    tone = 'bad';
    headline = 'Stopped — no brain can rule.';
    detail = s.providers.moat_blind;
  } else if (!producer && !consumer) {
    tone = 'bad';
    headline = 'Not running.';
    detail = `Producer: ${s.heartbeats.producer.why} Consumer: ${s.heartbeats.consumer.why}`;
  } else if (paused.length) {
    tone = 'warn';
    headline = paused.some((p) => p.scope === 'all') ? 'Paused — everything.' : 'Partly paused.';
    detail = paused
      .map((p) => `${p.scope}: stops ${p.stops}${p.reason ? ` (${p.reason})` : ''}`)
      .join(' · ');
  } else if (!producer || !consumer) {
    tone = 'warn';
    headline = producer ? 'Half running — the consumer is down.' : 'Half running — the producer is down.';
    detail = producer ? s.heartbeats.consumer.why : s.heartbeats.producer.why;
  } else if (alerts) {
    tone = 'warn';
    headline = `Running, with ${s.alerts.count} alert${s.alerts.count === 1 ? '' : 's'}.`;
    detail = s.alerts.banner || 'See the alert file.';
  } else if (stuck) {
    // Last, because everything above it stops the engine and this does not. It is still in the
    // headline: work dying silently is exactly the failure that had to be drilled for.
    tone = 'warn';
    headline = `Running, but ${stuck} ${stuck === 1 ? 'candidate' : 'candidates'} never finished.`;
    detail = 'They started and no verdict was ever written. See "Work that stopped" below.';
  }

  const edge = tone === 'ok' ? 'border-ok bg-ok-bg' : tone === 'warn' ? 'border-warn bg-warn-bg' : 'border-bad bg-bad-bg';
  const ink = tone === 'ok' ? 'text-ok-strong' : tone === 'warn' ? 'text-warn-strong' : 'text-bad-strong';

  return (
    <section className={`rounded-sm border ${edge} px-4 py-4`}>
      <div className={`text-[22px] font-[560] leading-tight ${ink}`}>{headline}</div>
      <p className="wrap-any mt-1 text-[13px] text-text">{detail}</p>
      {paused.length ? (
        <div className="mt-2 text-[12px] text-muted">
          {paused.map((p) => (
            <div key={p.scope}>
              armed {ago(p.armed_at)} by <span className="font-mono">{p.actor || 'unknown'}</span> · keeps
              running: {p.keeps_running}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function RoleRow({ hb, what }: { hb: Heartbeat; what: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border py-2 last:border-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="text-[14px]">{what}</div>
      <div className="flex items-center gap-2">
        <Pill tone={hb.alive ? 'ok' : 'bad'}>{hb.alive ? 'beating' : 'not beating'}</Pill>
        <span className="font-mono text-[12px] text-subtle">
          {hb.age_s === null ? ABSENT : `last beat ${duration(hb.age_s)} ago`}
        </span>
      </div>
      {!hb.alive ? <div className="wrap-any text-[12px] text-muted sm:w-full">{hb.why}</div> : null}
    </div>
  );
}
