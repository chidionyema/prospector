/**
 * Processes — everything this estate runs on a schedule, and what is failing.
 *
 * Why this page exists. The estate had no shortage of watchers: launchd jobs, GitHub workflows,
 * pre-commit gates, harness hooks, and half a dozen specialist probes. What it had no way to see
 * was whether any of them were still working. Each one reports only to itself, and each fails
 * silently in its own way — a launchd job's exit code lives only in `launchctl print`, a workflow
 * that is never triggered is never red, and a guard that gets switched off simply stops objecting.
 *
 * Measured on the day this page was written: five loaded jobs carried a non-zero last exit, two of
 * them for two days; four jobs were running that no file in this repo declared; two workflows had
 * never produced a single run; and the graph-freshness enforcement had been broken every thirty
 * minutes for long enough that nobody remembered it working.
 *
 * Nothing here is a new measurement. `scripts/process_audit.py` asks the tools that already own
 * each question and grades the answers, including whether the tool could answer at all. This page
 * renders that, and the same script sends the same verdict to Telegram when it fails.
 */
import Shell from '@/components/Shell';
import SnapshotBar, { type Snapshot } from '@/components/SnapshotBar';
import { AsOf, Card, Empty, Note, Pill, Problem, Scroll } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Grade = 'ok' | 'warn' | 'bad';

type ProcessRow = { grade: Grade; name: string; detail: string };

type ProcessesView = {
  generated_at: number;
  sections: { title: string; rows: ProcessRow[] }[];
  litter: string[];
  failing: number;
  warnings: number;
  ok: boolean;
  snapshot?: Snapshot;
};

/** The audit's grades and the console's tones are the same three words, deliberately. */
const TONE: Record<Grade, 'ok' | 'warn' | 'bad'> = { ok: 'ok', warn: 'warn', bad: 'bad' };
const LABEL: Record<Grade, string> = { ok: 'ok', warn: 'warn', bad: 'FAILING' };

function Section({ title, rows }: { title: string; rows: ProcessRow[] }) {
  // Worst first. A page that lists forty healthy jobs above the one that is down has buried it.
  const order: Record<Grade, number> = { bad: 0, warn: 1, ok: 2 };
  const sorted = [...rows].sort((a, b) => order[a.grade] - order[b.grade]);
  const failing = rows.filter((r) => r.grade === 'bad').length;
  return (
    <Card
      title={`${title} (${rows.length})`}
      tone={failing ? 'bad' : rows.some((r) => r.grade === 'warn') ? 'warn' : 'ok'}
      right={failing ? <Pill tone="bad">{failing} failing</Pill> : <Pill tone="ok">clean</Pill>}
    >
      {sorted.length === 0 ? (
        <Empty>nothing of this kind is installed</Empty>
      ) : (
        <Scroll>
          <table className="w-full text-sm">
            <tbody>
              {sorted.map((r) => (
                <tr key={r.name} className="border-b border-border last:border-0 align-top">
                  <td className="py-2 pr-3 whitespace-nowrap">
                    <Pill tone={TONE[r.grade]}>{LABEL[r.grade]}</Pill>
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap">{r.name}</td>
                  <td className="py-2 text-subtle">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}
    </Card>
  );
}

type AutomationRow = {
  automation: string;
  status: 'ok' | 'findings' | 'unknown';
  findings: number;
  summary: string;
  probe: string;
  took_ms: number;
  error?: string | null;
};

type AutomationsView = {
  count: number;
  needs_attention: number;
  automations: AutomationRow[];
  note?: string;
  snapshot?: Snapshot;
};

/** `unknown` is not `ok`. An automation that could not answer sorts and colours with the failures. */
const AUTO_TONE: Record<AutomationRow['status'], 'ok' | 'warn' | 'bad'> = {
  ok: 'ok',
  findings: 'warn',
  unknown: 'bad',
};

/**
 * The declared automations, each one run for real — as of the last measurement, not this render.
 *
 * `prospector/ops/automations_view.py` discovers every engine that has a declaration and runs its
 * `--json`, so this card needs no edit when the next automation lands. Retention (`log_rotation`)
 * is one of these: it freed 1,044 MB on its first scheduled run and nothing on this console showed
 * that it existed.
 *
 * It used to run all of them at the moment you opened the tab, for 10.16s measured. That was never
 * the right price for opening a tab, and the card above says how old the answer is instead.
 */
function Automations() {
  const { data, error, refresh } = useOps<AutomationsView>('automations', {}, { pollMs: 300_000 });
  if (error) return <Problem>{error}</Problem>;
  if (!data) return <Note>reading the last run of every automation</Note>;

  const rows = data.automations ?? [];
  const bar = (
    <SnapshotBar
      view="automations"
      snapshot={data.snapshot}
      what="every declared automation, run for real"
      onRefreshed={refresh}
    />
  );
  if (!data.snapshot?.have_snapshot) return bar;
  return (
    <>
      {bar}
    <Card
      title={`Automations (${data.count})`}
      tone={data.needs_attention ? 'warn' : 'ok'}
      right={
        data.needs_attention ? (
          <Pill tone="warn">{data.needs_attention} need attention</Pill>
        ) : (
          <Pill tone="ok">clean</Pill>
        )
      }
    >
      {rows.length === 0 ? (
        <Empty>{data.note ?? 'no automation has both an engine and a declaration here'}</Empty>
      ) : (
        <Scroll>
          <table className="w-full text-sm">
            <tbody>
              {rows.map((r) => (
                <tr key={r.automation} className="border-b border-border last:border-0 align-top">
                  <td className="py-2 pr-3 whitespace-nowrap">
                    <Pill tone={AUTO_TONE[r.status]}>{r.status}</Pill>
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap">{r.automation}</td>
                  <td className="py-2 text-subtle">
                    {r.error ? r.error : r.summary}
                    <div className="font-mono text-[11px] text-subtle/70 mt-1">{r.probe}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}
      <Note>
        Every one of these reads by default and takes <code>--fix</code> as a second, explicit run.
        Both are on <code>/tools</code>, behind the same preview and rollback as everything else.
      </Note>
    </Card>
    </>
  );
}

export default function Processes() {
  const { data, envelope, error, refresh } = useOps<ProcessesView>('processes', {}, {
    pollMs: 300_000,
  });

  return (
    <Shell
      title="Processes"
      intro="Everything scheduled on this estate, and whether it ran. Includes the guards themselves: a check that has been switched off is the one failure nothing else reports."
    >
      {error && <Problem>{error}</Problem>}
      {!data && !error && <Note>reading the last audit</Note>}

      {data && (
        <SnapshotBar
          view="processes"
          snapshot={data.snapshot}
          what="the estate audit — launchd, Fly, GitHub and every probe"
          onRefreshed={refresh}
        />
      )}

      {/*
        * Everything below is gated on there being a snapshot, and the "read N ago" stamp was
        * inside that gate. So the one page state where an operator most needs to know whether the
        * estate was heard from — no audit yet — was the state that would not tell them. Measured
        * 2026-08-21 by the e2e journey "every screen reads real data".
        */}
      {data && !data.snapshot?.have_snapshot && (
        <Card
          title="No audit has been taken yet"
          right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
        >
          <Note>
            The view answered and has no audit to show. That is not the same as the read failing:
            the stamp above says when this page last heard from the estate.
          </Note>
        </Card>
      )}

      {data?.snapshot?.have_snapshot && (
        <>
          <Card
            title="Verdict"
            tone={data.ok ? 'ok' : 'bad'}
            right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
          >
            {data.ok ? (
              <Note>Everything declared is running, and every guard is on.</Note>
            ) : (
              <Note>
                {data.failing} failing or undocumented, {data.warnings} warning(s). Run{' '}
                <code>python3 scripts/process_audit.py --quiet</code> for the same list in a
                terminal. Anything undocumented is fixed by adding a row to
                <code> docs/PROCESS_INVENTORY.md</code>.
              </Note>
            )}
          </Card>

          <Automations />

          {data.sections.map((s) => (
            <Section key={s.title} title={s.title} rows={s.rows} />
          ))}

          {data.litter.length > 0 && (
            <Card title={`Stale plist files (${data.litter.length})`} tone="warn">
              <Note>
                launchd ignores these, so they are not jobs. They are copies somebody kept, and
                they make ~/Library/LaunchAgents unreadable.
              </Note>
              <Scroll>
                <div className="font-mono text-xs text-subtle">{data.litter.join(', ')}</div>
              </Scroll>
            </Card>
          )}
        </>
      )}
    </Shell>
  );
}
