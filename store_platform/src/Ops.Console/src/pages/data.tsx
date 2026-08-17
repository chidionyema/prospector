/**
 * Data — if the Fly volume went away in the next minute, what comes back and what is lost.
 *
 * Four controls already answer this and none of them had a screen: the off-site backup check
 * (DAT-1), the restore drill (DAT-2), bucket versioning (AST-1) and the recovery window (DAT-4).
 * This page runs them and prints their answers.
 *
 * The rule this page exists to enforce: a check that could not run renders as `unknown` with its
 * reason, never as a pass. A backup screen that goes green when the credentials are missing is
 * the exact failure it is supposed to catch.
 */
import Shell from '@/components/Shell';
import { AsOf, Card, Note, Pill, Problem, Row, Stat } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Source = {
  name?: string;
  age_hours?: number | null;
  what?: string;
  bytes?: number | null;
  key?: string;
};
type Copy = {
  status: string;
  reason?: string | null;
  sources?: Source[];
  findings?: { what?: string }[];
};
type Drill = {
  state: 'ok' | 'stale' | 'failed' | 'never' | 'unreadable';
  path: string;
  ran_at: string | null;
  ok: boolean | null;
  age_days?: number | null;
  took_s?: number | null;
  restored?: string | null;
  what: string;
};
type Versioning = { state: 'on' | 'off' | 'unknown'; bucket?: string; raw?: string | null; reason?: string | null };
type DataView = {
  copy: Copy;
  drill: Drill;
  versioning: Versioning;
  rpo: { hours: number | null; what: string };
  warnings: string[];
};

const DRILL_TONE: Record<Drill['state'], 'ok' | 'warn' | 'bad'> = {
  ok: 'ok',
  stale: 'warn',
  failed: 'bad',
  never: 'bad',
  unreadable: 'warn',
};

const DRILL_WORDS: Record<Drill['state'], string> = {
  ok: 'A copy was restored and checked.',
  stale: 'The last drill is old enough that it is no longer evidence.',
  failed: 'The last drill did not restore. The copy is not proven to be recoverable.',
  never: 'No drill has ever run. A backup nobody has restored is an untested assumption.',
  unreadable: 'The receipt exists and cannot be read, so the drill counts as unproven.',
};

function copyTone(status: string): 'ok' | 'warn' | 'bad' {
  if (status === 'ok') return 'ok';
  if (status === 'unknown') return 'warn';
  return 'bad';
}

export default function Data() {
  const { data, envelope, error } = useOps<DataView>('data');
  const copy = data?.copy;
  const sources = copy?.sources ?? [];

  return (
    <Shell title="Data" intro="What survives if the volume is lost, and how much is lost with it.">
      {error ? <Problem>{error}</Problem> : null}
      {(data?.warnings ?? []).map((w) => (
        <Problem key={w}>{w}</Problem>
      ))}

      {data ? (
        <>
          <Card
            title="Off-site copy"
            tone={copyTone(copy?.status ?? 'unknown')}
            right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
          >
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat label="check" value={copy?.status} tone={copyTone(copy?.status ?? 'unknown')} />
              <Stat
                label="oldest copy"
                value={data.rpo.hours === null ? null : data.rpo.hours.toFixed(1)}
                unit="h"
                tone={data.rpo.hours === null ? 'warn' : 'plain'}
              />
              <Stat label="copies" value={sources.length || null} />
            </div>
            {copy?.reason ? <Note>{copy.reason}</Note> : null}
            <div className="mt-2">
              {sources.map((s, i) => (
                <Row key={s.key ?? s.name ?? i} label={s.name ?? s.key ?? `copy ${i + 1}`}>
                  {s.age_hours === null || s.age_hours === undefined
                    ? 'age unknown'
                    : `${s.age_hours.toFixed(1)}h old`}
                </Row>
              ))}
            </div>
            <p className="wrap-any mt-3 text-[13px] text-muted">
              Read with the backup automation&apos;s own check, in report mode. Opening this screen
              never takes a backup.
            </p>
          </Card>

          <Card title="Recovery point" tone={data.rpo.hours === null ? 'warn' : 'plain'}>
            <p className="wrap-any text-[13px] text-muted">{data.rpo.what}</p>
          </Card>

          <Card title="Restore drill" tone={DRILL_TONE[data.drill.state]}>
            <div className="flex items-baseline gap-2">
              <Pill tone={DRILL_TONE[data.drill.state]}>{data.drill.state}</Pill>
              <span className="wrap-any text-[13px] text-muted">
                {DRILL_WORDS[data.drill.state]}
              </span>
            </div>
            <div className="mt-2">
              <Row label="Last run">{data.drill.ran_at ?? 'never'}</Row>
              {data.drill.age_days === null || data.drill.age_days === undefined ? null : (
                <Row label="Age">{`${data.drill.age_days} days`}</Row>
              )}
              {data.drill.restored ? <Row label="Restored">{data.drill.restored}</Row> : null}
              <Row label="Receipt">{data.drill.path}</Row>
            </div>
            {data.drill.what ? <Note>{data.drill.what}</Note> : null}
            <p className="wrap-any mt-3 text-[13px] text-muted">
              The drill is <code className="font-mono">scripts/restore_drill.py</code>. It writes
              the receipt this panel reads.
            </p>
          </Card>

          <Card
            title="Bucket versioning"
            tone={
              data.versioning.state === 'on'
                ? 'ok'
                : data.versioning.state === 'off'
                  ? 'bad'
                  : 'warn'
            }
          >
            <div className="flex items-baseline gap-2">
              <Pill
                tone={
                  data.versioning.state === 'on'
                    ? 'ok'
                    : data.versioning.state === 'off'
                      ? 'bad'
                      : 'warn'
                }
              >
                {data.versioning.state}
              </Pill>
              {data.versioning.bucket ? (
                <span className="wrap-any font-mono text-[12px] text-subtle">
                  {data.versioning.bucket}
                </span>
              ) : null}
            </div>
            <p className="wrap-any mt-2 text-[13px] text-muted">
              {data.versioning.state === 'on'
                ? 'An overwrite or a delete can be rolled back.'
                : data.versioning.state === 'off'
                  ? 'Without versioning, one bad sync overwrites the copy that was the safety net.'
                  : 'The bucket could not be asked, so versioning is unknown, not on.'}
            </p>
            {data.versioning.reason ? <Note>{data.versioning.reason}</Note> : null}
          </Card>
        </>
      ) : (
        <Card>running the backup checks…</Card>
      )}
    </Shell>
  );
}
