/**
 * Tools — every operator command in the repo, runnable from here.
 *
 * The inventory is a hand-written table in `prospector/ops/console_api.py` (`TOOLS`), not a
 * directory scan, for one reason: a scan can say a file exists but cannot say what it does to your
 * data. `exists` IS measured on disk, so a tool that gets deleted or renamed shows up as missing
 * instead of quietly staying in the list.
 *
 * THIS PAGE USED TO SAY "Nothing on this page runs." That was the wrong fence (founder directive,
 * 2026-08-16: "we just need rollback to be safe not to hide actions"). A tool the console refused
 * was not a tool that did not run — it was a tool the operator ran at a terminal instead, with no
 * preview, no receipt and no undo. Hiding it made the estate less safe, not more.
 *
 * What makes it safe now is the same gate every other write goes through, plus one addition:
 *   1. the console still executes exactly ONE command, `python -m prospector.ops.console_api`;
 *   2. the tool's command comes from the Python table, never from the browser — the browser sends
 *      an id and values for named placeholders, so this is not a web shell;
 *   3. preview, then a confirmation token bound to that exact payload, then a receipt;
 *   4. a rollback snapshot of store/ is taken before anything that writes, and the Undo card at
 *      the top of this page puts it back.
 *
 * `risk` is the honest part. "local" means undo covers everything the tool wrote. "external" means
 * the tool reaches Stripe, the live shelf or R2, and undo covers the local half only.
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Mono, Note, Pill, Problem, Row, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Risk = 'read' | 'local' | 'external' | 'shell';

type Tool = {
  id: string;
  path: string;
  purpose: string;
  writes: boolean;
  screen: string;
  run: boolean;
  risk: Risk;
  undo_covers: string;
  danger: string | null;
  command: string;
  exists: boolean;
};

type ToolsView = { root: string; tools: Tool[]; note: string };

type Snapshot = {
  id: string;
  ts: string;
  label: string;
  files?: number;
  bytes?: number;
  broken?: boolean;
};

type UndoView = { snapshots: Snapshot[]; count: number; keep: number; covers: string };

const SCREEN_NAME: Record<string, string> = {
  '/': 'Now',
  '/engine': 'Engine',
  '/config': 'Settings',
  '/queue': 'Queue',
  '/runs': 'Runs',
  '/spend': 'Spend',
  '/metrics': 'Yield',
  '/catalogue': 'Shelf',
  '/tools': 'Tools',
  '/audit': 'Audit',
};

/** What each risk word means to the person about to press the button. */
const RISK_NOTE: Record<Risk, string> = {
  read: 'reads only — nothing to undo',
  local: 'undo puts this back in full',
  external: 'reaches off this machine — undo covers the local half only',
  shell: 'a daemon, not a tool',
};

const RISK_TONE: Record<Risk, 'mute' | 'ok' | 'warn' | 'bad'> = {
  read: 'mute',
  local: 'ok',
  external: 'bad',
  shell: 'mute',
};

/** `<idea>` in a catalogued command is a value the operator must supply before it can run. */
function placeholdersOf(command: string): string[] {
  return [...command.matchAll(/<([a-z0-9_]+)>/g)].map((m) => m[1]);
}

type JobView = {
  job: string;
  state: 'running' | 'finished' | 'timed_out' | 'lost' | 'unknown';
  rows: number;
  age_s: number | null;
  note: string;
  receipt: {
    exit_code?: number | null;
    took_s?: number;
    message?: string;
    undo_id?: string | null;
  } | null;
};

const JOB_TONE: Record<JobView['state'], 'mute' | 'ok' | 'warn' | 'bad'> = {
  running: 'warn',
  finished: 'ok',
  timed_out: 'bad',
  lost: 'bad',
  unknown: 'mute',
};

/**
 * A tool run in progress, and its receipt when it lands.
 *
 * The run is a BACKGROUND job: `tools.run` returns a job id immediately and the tool keeps going
 * whether or not this page is open. So this polls rather than waits — closing the tab, losing wifi
 * or restarting the console does not kill the run, and reopening the page picks the job back up.
 * Its own component because a hook cannot live inside the tool list's map().
 */
/** A job in one of these states will never change again, so the poll must stop on it. */
function hasEnded(data: JobView | null): boolean {
  const state = data?.state ?? 'unknown';
  return state === 'finished' || state === 'timed_out' || state === 'lost';
}

function JobWatch({ job, onFinished }: { job: string; onFinished: () => void }) {
  // THE POLL STOPS WHEN THE JOB DOES. Every read spawns a Python gateway process (measured ~850ms
  // on this box), so a page left open on a finished job would spawn 900 subprocesses an hour to
  // re-read a receipt that cannot change. `useOps` treats pollMs 0 as "do not poll".
  const live = useOps<JobView>('job', { job }, { pollMs: 4000, stopWhen: hasEnded });
  const state = live.data?.state ?? 'unknown';
  const receipt = live.data?.receipt ?? null;
  const ended = hasEnded(live.data ?? null);

  // Refresh the undo list once, when the run ends: a tool that wrote may have added a snapshot.
  // The ref is written inside the effect, never during render — a ref read or written while
  // rendering can leave the component showing a value it never re-rendered for.
  const notified = useRef(false);
  useEffect(() => {
    if (!ended || notified.current) return;
    notified.current = true;
    onFinished();
  }, [ended, onFinished]);

  return (
    <div className="mt-2 flex flex-col gap-1 rounded-sm border border-border bg-surface2 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <Pill tone={JOB_TONE[state]}>{state === 'running' ? 'running' : state}</Pill>
        <Mono>job {job}</Mono>
        {live.data?.age_s != null ? (
          <span className="text-subtle">{Math.round(live.data.age_s)}s</span>
        ) : null}
        {receipt?.exit_code != null ? (
          <span className={receipt.exit_code === 0 ? 'text-ok-strong' : 'text-bad-strong'}>
            exit {receipt.exit_code}
          </span>
        ) : null}
      </div>
      {live.error ? <Problem>{live.error}</Problem> : null}
      <div className="text-[12px] text-muted">{live.data?.note ?? ''}</div>
      {ended && receipt?.message ? (
        <pre tabIndex={0} className="scroll-x mt-1 max-h-56 overflow-y-auto rounded-sm bg-surface3 px-2 py-1.5 font-mono text-[11px]">
          {receipt.message}
        </pre>
      ) : null}
    </div>
  );
}

function fmtBytes(n?: number): string {
  if (!n) return '—';
  if (n > 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n > 1e6) return `${(n / 1e6).toFixed(0)} MB`;
  return `${(n / 1e3).toFixed(0)} kB`;
}

export default function Tools() {
  const { data, envelope, error, refresh } = useOps<ToolsView>('tools');
  const undo = useOps<UndoView>('undo');
  const [q, setQ] = useState('');
  const [onlyWrites, setOnlyWrites] = useState(false);
  // Placeholder values, keyed by tool id then placeholder name. Kept here rather than in each row
  // so a re-render from the search box does not wipe what the operator typed.
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});

  const setValue = (toolId: string, name: string, v: string) =>
    setValues((prev) => ({ ...prev, [toolId]: { ...(prev[toolId] ?? {}), [name]: v } }));

  // The background job each tool started in this session, so the row can show how it is going.
  const [jobs, setJobs] = useState<Record<string, string>>({});
  const setJob = (toolId: string, job: string) =>
    setJobs((prev) => ({ ...prev, [toolId]: job }));

  const groups = useMemo(() => {
    const rows = (data?.tools ?? []).filter((t) => {
      if (onlyWrites && !t.writes) return false;
      const needle = q.trim().toLowerCase();
      if (!needle) return true;
      return [t.path, t.purpose, t.command, t.screen].join(' ').toLowerCase().includes(needle);
    });
    const by = new Map<string, Tool[]>();
    for (const t of rows) {
      if (!by.has(t.screen)) by.set(t.screen, []);
      by.get(t.screen)!.push(t);
    }
    return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [data, q, onlyWrites]);

  const missing = (data?.tools ?? []).filter((t) => !t.exists);
  const runnable = (data?.tools ?? []).filter((t) => t.run).length;
  const snapshots = undo.data?.snapshots ?? [];

  return (
    <Shell title="Tools" intro="Every operator command in the repo. Run them here, undo them here.">
      {error ? <Problem>{error}</Problem> : null}
      {!data ? (
        <Card>
          <Spinner what="reading the tool table" />
        </Card>
      ) : null}

      <Card title="Undo">
        <p className="text-[13px] text-muted">
          A snapshot of the local store is taken before any tool that writes. Rolling back restores
          what changed <strong>and deletes what was written since</strong> — if the engine is
          running, arm a pause first or you roll back its work too.
        </p>
        {snapshots.length === 0 ? (
          <Empty>No rollback point yet. One is created the first time you run a tool that writes.</Empty>
        ) : (
          <div className="mt-2 flex flex-col gap-2">
            {snapshots.slice(0, 5).map((s) => (
              <div key={s.id} className="rounded-sm border border-border px-3 py-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[14px] font-[520]">{s.label}</span>
                  <span className="text-[12px] text-subtle">
                    {s.files ?? '—'} files · {fmtBytes(s.bytes)}
                  </span>
                </div>
                <Mono>{s.id}</Mono>
                <div className="mt-2">
                  <Confirm
                    action="tools.undo"
                    kind="danger"
                    label="Roll back to this"
                    disabled={Boolean(s.broken)}
                    payload={() => ({
                      snapshot: s.id,
                      actor: 'console',
                      reason: `roll back ${s.label}`,
                    })}
                    renderPreview={(p) => (
                      <div className="flex flex-col gap-1">
                        <div>{String(p.effect ?? '')}</div>
                        <div className="text-[13px]">
                          restore {String(p.restore ?? '?')} · delete {String(p.delete ?? '?')} ·
                          unchanged {String(p.unchanged ?? '?')}
                        </div>
                        <Note>{String(p.warning ?? '')}</Note>
                      </div>
                    )}
                    onApplied={() => {
                      undo.refresh();
                      refresh();
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
        {undo.data ? <Note>{undo.data.covers}</Note> : null}
      </Card>

      {data ? (
        <Card title="Inventory" right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}>
          <Row label="Tools listed">{data.tools.length}</Row>
          <Row label="Runnable from here">{runnable}</Row>
          <Row label="That change data">{data.tools.filter((t) => t.writes).length}</Row>
          <Row label="Missing from disk">{missing.length}</Row>
          <Note>{data.note}</Note>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="find a tool…"
            className="tap mt-3 w-full rounded-sm border border-border bg-surface px-3 text-[16px]"
          />
          <label className="mt-2 flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={onlyWrites}
              onChange={(e) => setOnlyWrites(e.target.checked)}
              className="h-4 w-4"
            />
            only the ones that change data
          </label>
        </Card>
      ) : null}

      {missing.length > 0 ? (
        <Card title={`${missing.length} listed tool(s) are not on disk`} tone="warn">
          <p className="text-[13px] text-muted">
            The table names them and the file is gone. Either the tool was deleted and this table is
            stale, or the checkout is incomplete.
          </p>
          {missing.map((t) => (
            <div key={t.path + t.purpose} className="wrap-any mt-1 font-mono text-[12px]">
              {t.path}
            </div>
          ))}
        </Card>
      ) : null}

      {groups.length === 0 && data ? (
        <Card>
          <Empty>No tool matches that.</Empty>
        </Card>
      ) : null}

      {groups.map(([screen, tools]) => (
        <Card key={screen} title={SCREEN_NAME[screen] ?? screen}>
          <div className="text-[12px] text-subtle">
            {screen === '/tools' ? 'No other screen covers these.' : `Also covered by ${screen}.`}
          </div>
          <div className="mt-2 flex flex-col gap-3">
            {tools.map((t) => {
              const needs = placeholdersOf(t.command);
              const given = values[t.id] ?? {};
              const ready = needs.every((n) => (given[n] ?? '').trim() !== '');
              return (
                <div key={t.id} className="rounded-sm border border-border px-3 py-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-[14px] font-[520]">{t.purpose}</span>
                    <div className="flex shrink-0 gap-1.5">
                      <Pill tone={RISK_TONE[t.risk]}>{t.risk}</Pill>
                      {t.exists ? null : <Pill tone="bad">missing</Pill>}
                    </div>
                  </div>
                  <div className="wrap-any mt-1 font-mono text-[11px] text-subtle">{t.path}</div>
                  <pre tabIndex={0} className="scroll-x mt-2 rounded-sm bg-surface3 px-2 py-1.5 font-mono text-[11px]">
                    {t.command}
                  </pre>
                  <div className="mt-1 text-[12px] text-muted">{RISK_NOTE[t.risk]}</div>
                  {t.danger ? (
                    <div className="mt-1 text-[12px] text-bad-strong">care: {t.danger}</div>
                  ) : null}

                  {needs.length > 0 && t.run ? (
                    <div className="mt-2 flex flex-col gap-1.5">
                      {needs.map((n) => (
                        <label key={n} className="flex flex-col gap-1 text-[12px] text-muted">
                          {n}
                          <input
                            value={given[n] ?? ''}
                            onChange={(e) => setValue(t.id, n, e.target.value)}
                            placeholder={`value for <${n}>`}
                            className="tap w-full rounded-sm border border-border bg-surface px-3 text-[16px]"
                          />
                        </label>
                      ))}
                    </div>
                  ) : null}

                  <div className="mt-2">
                    {t.run && t.exists ? (
                      <Confirm
                        action="tools.run"
                        kind={t.risk === 'external' ? 'danger' : 'primary'}
                        label="Run"
                        disabled={!ready}
                        payload={() => ({
                          id: t.id,
                          actor: 'console',
                          reason: t.purpose,
                          ...given,
                        })}
                        renderPreview={(p) => (
                          <div className="flex flex-col gap-1">
                            <div>{String(p.effect ?? '')}</div>
                            <Mono>{String(p.command ?? '')}</Mono>
                            <div className="text-[13px]">
                              undo: {String(p.undo_covers ?? '')} · {String(p.snapshot ?? '')}
                            </div>
                            <Note>{String(p.note ?? '')}</Note>
                          </div>
                        )}
                        onApplied={(receipt) => {
                          undo.refresh();
                          const job = receipt?.job;
                          if (typeof job === 'string' && job) setJob(t.id, job);
                        }}
                      />
                    ) : (
                      <div className="text-[12px] text-subtle">
                        {t.exists
                          ? `not runnable here — ${t.danger ?? 'see the command above'}`
                          : 'the file is missing, so there is nothing to run'}
                      </div>
                    )}
                    {jobs[t.id] ? (
                      <JobWatch job={jobs[t.id]} onFinished={() => undo.refresh()} />
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      ))}

      {data ? (
        <Card title="Where these live">
          <Row label="Repo">
            <span className="wrap-any font-mono text-[12px]">{data.root}</span>
          </Row>
        </Card>
      ) : null}
    </Shell>
  );
}
