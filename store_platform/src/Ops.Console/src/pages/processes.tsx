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

export default function Processes() {
  const { data, envelope, error } = useOps<ProcessesView>('processes', {}, { pollMs: 300_000 });

  return (
    <Shell
      title="Processes"
      intro="Everything scheduled on this estate, and whether it ran. Includes the guards themselves: a check that has been switched off is the one failure nothing else reports."
    >
      {error && <Problem>{error}</Problem>}
      {!data && !error && <Note>reading the audit — it asks launchd, GitHub and every probe</Note>}

      {data && (
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
