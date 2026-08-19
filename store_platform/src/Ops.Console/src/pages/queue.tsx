/**
 * Queue — what is waiting, how old the oldest thing is, and whether it is moving.
 *
 * "Backlog" here is exactly `run.drainable()`, which is the single definition in the engine. A
 * count the drain cannot move is not backlog, and showing one would make the brake look wrong
 * every time it declined to fire.
 *
 * Founder requirement: the age of the oldest waiting item is on the page. A queue depth with no
 * age on it cannot distinguish a busy hour from a three-week stall.
 *
 * And since 2026-08-18 the PROCESS is on the page too. Founder: "the consumer is a mystery ... if
 * I asked what it is doing right now and how long left, I don't know." The page showed a rate and
 * an ETA with nothing about the thing producing them, so a consumer wedged mid-pass for an hour
 * and a consumer working normally rendered identically.
 */
import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Card, Note, Pill, Problem, Row, Scroll, Stat } from '@/components/ui';
import { ABSENT, ago, clock, duration } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type QueueView = {
  now: string;
  by_decision: Record<string, number>;
  backlog: {
    workable: number;
    orphaned: number;
    stalled: number;
    unpublishable: number;
    oldest_created_at: string | null;
  };
  leases: { held: number; expired: number; unheld: number; total: number };
  consumer: {
    state: string;
    reason: string;
    phase: string | null;
    pid: number | null;
    alive: boolean;
    cycle: number | null;
    batch: number | null;
    resumed_total: number | null;
    phase_age_s: number | null;
    says: string;
  };
  drain: {
    events: number;
    attempted: number;
    resumed: number;
    window_h: number | null;
    rate_per_h: number | null;
    eta_h: number | null;
    eta_at: string | null;
    eta_reason: string;
    caveat: string;
    sources: string[];
    outcomes: {
      passes: number;
      kills: number;
      defers: number;
      leased_skipped: number;
      metered_usd: number;
      backlog_then: number | null;
      backlog_now: number;
      moved: number | null;
    };
    recent: {
      ts: string;
      source: string;
      attempted: number | null;
      resumed: number | null;
      passes: number | null;
      kills: number | null;
      defers: number | null;
      backlog: number | null;
      metered_usd: number | null;
    }[];
  };
};

/**
 * The give-up ledger, read from the box the engine is actually running on.
 *
 * `side` and `active_side` are both on the payload and both are rendered. On 2026-08-19 this
 * console read the laptop store and reported an empty ledger while the Fly engine carried 251
 * permanently retired rows. A number with no box named against it is what made that possible.
 */
type DrainView = {
  side: string;
  active_side: string;
  store_dir: string;
  ledger_path: string;
  ledger_exists: boolean;
  max_attempts: number;
  rows: number;
  histogram: Record<string, number>;
  retired: string[];
  retired_count: number;
  warnings: string[];
  incident: string;
  error: string | null;
};

/** How the consumer's state reads as a colour. `late` is amber, not red: alive and slow is not
 *  the same fault as gone, and treating them alike is how a real death gets ignored. */
function consumerTone(state: string): 'ok' | 'warn' | 'bad' | 'mute' {
  if (state === 'running') return 'ok';
  if (state === 'late' || state === 'blocked') return 'warn';
  if (state === 'dead') return 'bad';
  return 'mute';
}

export default function Queue() {
  // 15s. This is the page someone sits on while they wait for the queue to move, so it is
  // one of the two fastest panels in the console (the other is the brains on Engine).
  const { data, envelope, error } = useOps<QueueView>('queue', {}, { pollMs: 15_000 });
  // Two minutes, not fifteen seconds: this one SSHes into the active engine to read its
  // ledger and measured 4.6s on 2026-08-19. It is a number that changes once a tick at most.
  const drain = useOps<DrainView>('drain', {}, { pollMs: 120_000 });

  return (
    <Shell title="Queue" intro="Work the engine has taken on and not yet finished.">
      {error ? <Problem>{error}</Problem> : null}
      {!data ? <Card>reading the queue…</Card> : null}

      {data ? (
        <Card
          title="What the consumer is doing right now"
          right={<Pill tone={consumerTone(data.consumer.state)}>{data.consumer.state}</Pill>}
        >
          <p className="text-[14px]">{data.consumer.says}</p>
          <div className="mt-3">
            <Row label="Phase">
              {data.consumer.phase ?? ABSENT}
              {data.consumer.phase_age_s !== null
                ? ` · for ${duration(data.consumer.phase_age_s)}`
                : ''}
            </Row>
            <Row label="Process">
              {data.consumer.pid ? `pid ${data.consumer.pid}` : ABSENT}
              {data.consumer.alive ? ' · alive' : ' · not running'}
            </Row>
            <Row label="This run">
              {data.consumer.cycle ?? 0} pass(es), {data.consumer.resumed_total ?? 0} row(s) picked
              up, {data.consumer.batch ?? 0} per batch
            </Row>
          </div>
          {data.consumer.state === 'late' ? (
            <Problem>
              The beat is older than the consumer promised. It is alive, so it is stuck inside one
              call rather than gone — the queue is not moving while this lasts.
            </Problem>
          ) : null}
          {data.consumer.reason && data.consumer.state !== 'running' ? (
            <Note>{data.consumer.reason}</Note>
          ) : null}
        </Card>
      ) : null}

      {data ? (
        <Card
          title="Waiting"
          right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
        >
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat
              label="workable"
              value={data.backlog.workable}
              note="what the drain can move"
              tone={data.backlog.workable > 0 ? 'plain' : 'ok'}
            />
            <Stat
              label="stalled"
              value={data.backlog.stalled}
              note="out of re-vet budget"
              tone={data.backlog.stalled ? 'warn' : 'plain'}
            />
            <Stat
              label="orphaned"
              value={data.backlog.orphaned}
              note="no candidate behind the row"
              tone={data.backlog.orphaned ? 'warn' : 'plain'}
            />
            <Stat
              label="unpublishable"
              value={data.backlog.unpublishable}
              note="would never reach the shelf"
            />
          </div>

          <div className="mt-4">
            <Row label="Oldest waiting item">
              {data.backlog.oldest_created_at ? (
                <>
                  {clock(data.backlog.oldest_created_at)} · {ago(data.backlog.oldest_created_at)}
                </>
              ) : (
                ABSENT
              )}
            </Row>
            <Row label="Leases held right now">
              {data.leases.held} of {data.leases.total}
              {data.leases.expired ? ` · ${data.leases.expired} expired` : ''}
            </Row>
          </div>
        </Card>
      ) : null}

      <Card
        title="Given up on"
        right={
          drain.data ? (
            <Pill tone={drain.data.retired_count ? 'bad' : 'ok'}>
              {drain.data.side}
              {drain.data.side !== drain.data.active_side ? ' (not the active side)' : ''}
            </Pill>
          ) : null
        }
      >
        {drain.error ? <Problem>{drain.error}</Problem> : null}
        {!drain.data && !drain.error ? <div>reading the active engine…</div> : null}
        {drain.data ? (
          <>
            <p className="text-[14px]">
              A candidate leaves the queue for good after {drain.data.max_attempts} completed
              re-vets that did not resolve it. Nothing puts it back.
            </p>
            <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat
                label="retired"
                value={drain.data.retired_count}
                note="will never be worked again"
                tone={drain.data.retired_count ? 'warn' : 'ok'}
              />
              <Stat label="rows tracked" value={drain.data.rows} note="have been tried at least once" />
              <Stat label="give-up cap" value={drain.data.max_attempts} note="attempts per row" />
            </div>
            {Object.keys(drain.data.histogram).length ? (
              <div className="mt-3">
                <Row label="Attempts spent">
                  {Object.entries(drain.data.histogram)
                    .sort((a, b) => Number(a[0]) - Number(b[0]))
                    .map(([n, count]) => `${n}x: ${count}`)
                    .join(' · ')}
                </Row>
              </div>
            ) : null}
            <div className="mt-3">
              <Row label="Read from">
                <span className="font-mono text-[12px]">{drain.data.ledger_path}</span> on{' '}
                {drain.data.side}
              </Row>
              <Row label="Engine is on">{drain.data.active_side}</Row>
            </div>
            {drain.data.warnings.map((w) => (
              <Problem key={w}>{w}</Problem>
            ))}
            <Note>
              Until PR #356 an outage of our own spent a row&rsquo;s budget like a real attempt, so
              251 candidates were retired for our downtime rather than on their merits. The counter
              ignores infrastructure defers now, but no code hands back a budget already spent —
              that is what the reset below is for. Record:{' '}
              <span className="font-mono text-[11px]">{drain.data.incident}</span>
            </Note>
            <div className="mt-3">
              <Confirm
                action="drain.reset"
                kind="danger"
                label="Hand every row its budget back"
                applyLabel="Yes, clear the ledger"
                disabled={!drain.data.rows}
                payload={() => ({ side: 'active' })}
                requireAck={(p) =>
                  Number(p.rows ?? 0) > 0
                    ? `I understand this puts ${p.rows} row(s) back to zero attempts on ${String(
                        p.side ?? '',
                      )} and the engine will spend money re-vetting them.`
                    : null
                }
                renderPreview={(p) => (
                  <div className="flex flex-col gap-1">
                    <div className="font-[560]">{String(p.effect ?? '')}</div>
                    <div>Cost: {String(p.cost ?? '')}</div>
                    <div>Backup: {String(p.backup ?? '')}</div>
                    <div>Reversible: {String(p.reversible ?? '')}</div>
                    <div className="font-mono text-[11px]">{String(p.ledger_path ?? '')}</div>
                  </div>
                )}
                onApplied={drain.refresh}
              />
            </div>
          </>
        ) : null}
      </Card>

      {data ? (
        <Card title="Is it moving?">
          {data.drain.rate_per_h === null ? (
            <Note>{data.drain.eta_reason}</Note>
          ) : (
            <>
              <Row label="Rate">{data.drain.rate_per_h}/hour</Row>
              <Row label="Resumed in window">
                {data.drain.resumed} of {data.drain.attempted} attempted
                {data.drain.window_h ? ` over ${duration(data.drain.window_h * 3600)}` : ''}
              </Row>
              <Row label="Empty in">
                {data.drain.eta_h === null ? data.drain.eta_reason : duration(data.drain.eta_h * 3600)}
              </Row>
              {data.drain.eta_at ? <Row label="That is">{clock(data.drain.eta_at)}</Row> : null}
            </>
          )}
          <div className="mt-3 border-t border-border pt-3">
            <Row label="What came of it">
              {data.drain.outcomes.passes} finished, {data.drain.outcomes.kills} killed,{' '}
              {data.drain.outcomes.defers} parked again
            </Row>
            <Row label="Backlog then and now">
              {data.drain.outcomes.backlog_then ?? ABSENT} → {data.drain.outcomes.backlog_now}
              {data.drain.outcomes.moved !== null
                ? ` · ${data.drain.outcomes.moved > 0 ? 'down' : 'up'} ${Math.abs(
                    data.drain.outcomes.moved,
                  )}`
                : ''}
            </Row>
            <Row label="Spent on it">${data.drain.outcomes.metered_usd.toFixed(2)}</Row>
          </div>
          {data.drain.caveat ? <Note>{data.drain.caveat}</Note> : null}
          {data.drain.sources?.length ? (
            <div className="mt-2 text-[11px] text-subtle">
              counted from: {data.drain.sources.join(', ')}
            </div>
          ) : null}
        </Card>
      ) : null}

      {data && data.drain.recent.length ? (
        <Card title="The last few passes">
          <Scroll>
            <table className="w-full text-left font-mono text-[12px]">
              <thead className="text-subtle">
                <tr>
                  <th className="py-1 pr-3 font-normal">when</th>
                  <th className="py-1 pr-3 font-normal">picked up</th>
                  <th className="py-1 pr-3 font-normal">finished</th>
                  <th className="py-1 pr-3 font-normal">killed</th>
                  <th className="py-1 pr-3 font-normal">parked again</th>
                  <th className="py-1 pr-3 font-normal">backlog after</th>
                  <th className="py-1 font-normal">spent</th>
                </tr>
              </thead>
              <tbody>
                {data.drain.recent.map((r, i) => (
                  <tr key={`${r.ts}-${i}`} className="border-t border-border">
                    <td className="py-1 pr-3 whitespace-nowrap">{ago(r.ts)}</td>
                    <td className="py-1 pr-3">{r.resumed ?? 0}</td>
                    <td className="py-1 pr-3">{r.passes ?? 0}</td>
                    <td className="py-1 pr-3">{r.kills ?? 0}</td>
                    <td className="py-1 pr-3">{r.defers ?? 0}</td>
                    <td className="py-1 pr-3">{r.backlog ?? ABSENT}</td>
                    <td className="py-1">${(r.metered_usd ?? 0).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <Note>
            Rows that were picked up but neither finished nor killed were parked again. A column of
            those with a flat backlog is the drain re-reading the same work, not making progress.
          </Note>
        </Card>
      ) : null}

      {data && Object.keys(data.by_decision).length ? (
        <Card title="Everything in the catalogue, by verdict">
          <Scroll>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(data.by_decision).map(([k, v]) => (
                <Pill key={k} tone={k === 'pass' ? 'ok' : k === 'kill' ? 'bad' : 'mute'}>
                  {k} {v}
                </Pill>
              ))}
            </div>
          </Scroll>
        </Card>
      ) : null}
    </Shell>
  );
}
