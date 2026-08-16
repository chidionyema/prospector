/**
 * Queue — what is waiting, how old the oldest thing is, and whether it is moving.
 *
 * "Backlog" here is exactly `run.drainable()`, which is the single definition in the engine. A
 * count the drain cannot move is not backlog, and showing one would make the brake look wrong
 * every time it declined to fire.
 *
 * Founder requirement: the age of the oldest waiting item is on the page. A queue depth with no
 * age on it cannot distinguish a busy hour from a three-week stall.
 */
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
  };
};

export default function Queue() {
  const { data, envelope, error } = useOps<QueueView>('queue', {}, { pollMs: 60_000 });

  return (
    <Shell title="Queue" intro="Work the engine has taken on and not yet finished.">
      {error ? <Problem>{error}</Problem> : null}
      {!data ? <Card>reading the queue…</Card> : null}

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
              note="tried too many times"
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
          {data.drain.caveat ? <Note>{data.drain.caveat}</Note> : null}
          {data.drain.sources?.length ? (
            <div className="mt-2 text-[11px] text-subtle">
              counted from: {data.drain.sources.join(', ')}
            </div>
          ) : null}
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
