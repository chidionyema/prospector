/**
 * Deploys — when each deployable last shipped, and whether anything is stuck on the way out.
 *
 * Why this page exists. On 2026-08-19 a merge to `main` sat undeployed for twelve hours while
 * every check anyone could run said green: the PR was merged, the local suite passed, the deploy
 * run existed. The site served the old build the whole time, because the run was queued. Nothing
 * in the console compared what is on `main` with what the live apps are running, so the only way
 * to see it was to read a Fly release list by hand.
 *
 * Nothing here is computed in the browser. `scripts/deploy_status.py` reads each workflow's own
 * trigger paths, the last successful run's head commit, the live Fly release and the commits on
 * origin/main since — and this renders that. UNKNOWN is shown as a problem, never as silence.
 */
import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Scroll } from '@/components/ui';
import { ago } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type State = 'LIVE' | 'SHIPPING' | 'STALLED' | 'FAILED' | 'DRIFTED' | 'UNKNOWN';

type Deployable = {
  name: string;
  what: string;
  state: State;
  why: string;
  app: string | null;
  url?: string | null;
  workflow?: string | null;
  deployed_sha?: string;
  deployed_at?: string | null;
  deployed_how?: string;
  deployed_run_url?: string;
  fly_version?: number;
  fly_at?: string | null;
  pending_commits?: { sha: string; at: string; subject: string }[];
  running?: { status: string; url: string; sha: string; age_s: number | null }[];
};

type Fleet = {
  app: string;
  machines: { id: string; state: string; region: string }[];
  stopped: { id: string; state: string }[];
  queued: { workflow: string; url: string; age_s: number | null }[];
  oldest_queued_s: number;
  problem?: string;
  error?: string | null;
};

type DeploysView = {
  at: string;
  deployables: Deployable[];
  runners: Fleet;
  headline: string;
  needs_attention: number;
  fixed?: string[];
};

/** The probe's six states, and how loudly each one should read. */
const TONE: Record<State, 'ok' | 'warn' | 'bad'> = {
  LIVE: 'ok',
  SHIPPING: 'warn',
  STALLED: 'bad',
  FAILED: 'bad',
  DRIFTED: 'warn',
  UNKNOWN: 'bad',
};

function Deployable({ d }: { d: Deployable }) {
  const pending = d.pending_commits ?? [];
  return (
    <Card
      title={d.name}
      tone={TONE[d.state]}
      right={<Pill tone={TONE[d.state]}>{d.state}</Pill>}
    >
      <Note>{d.what}</Note>
      <table className="w-full text-sm mt-2">
        <tbody>
          <tr className="border-b border-border align-top">
            <td className="py-2 pr-3 text-subtle whitespace-nowrap">last deployed</td>
            <td className="py-2">
              {d.deployed_at ? ago(d.deployed_at) : 'never, or not recorded'}
              {d.deployed_sha && <span className="font-mono text-xs"> · {d.deployed_sha}</span>}
              {d.deployed_how && <span className="text-subtle"> · {d.deployed_how}</span>}
            </td>
          </tr>
          {d.fly_at && (
            <tr className="border-b border-border align-top">
              <td className="py-2 pr-3 text-subtle whitespace-nowrap">Fly release</td>
              <td className="py-2">
                v{d.fly_version} · {ago(d.fly_at)}
                {d.app && <span className="font-mono text-xs text-subtle"> · {d.app}</span>}
              </td>
            </tr>
          )}
          <tr className="align-top">
            <td className="py-2 pr-3 text-subtle whitespace-nowrap">why</td>
            <td className="py-2">{d.why}</td>
          </tr>
        </tbody>
      </table>

      {(d.running ?? []).length > 0 && (
        <Note>
          running now:{' '}
          {(d.running ?? []).map((r) => (
            <a key={r.url} href={r.url} className="underline mr-2" target="_blank" rel="noreferrer">
              {r.status} · {r.sha}
            </a>
          ))}
        </Note>
      )}

      {pending.length > 0 && (
        <Scroll>
          <table className="w-full text-sm mt-2">
            <tbody>
              {pending.slice(0, 10).map((c) => (
                <tr key={c.sha} className="border-b border-border last:border-0 align-top">
                  <td className="py-1 pr-3 font-mono text-xs whitespace-nowrap">{c.sha}</td>
                  <td className="py-1 pr-3 text-subtle whitespace-nowrap">{ago(c.at)}</td>
                  <td className="py-1">{c.subject}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pending.length > 10 && <Note>and {pending.length - 10} more waiting</Note>}
        </Scroll>
      )}
    </Card>
  );
}

export default function Deploys() {
  const { data, envelope, error } = useOps<DeploysView>('deploys', {}, { pollMs: 300_000 });
  const fleet = data?.runners;

  return (
    <Shell
      title="Deploys"
      intro="What each deployable is running, and how far behind main it is. A merge is not a deploy: this is the page that says whether the live site has the commit yet."
    >
      {error && <Problem>{error}</Problem>}
      {!data && !error && <Note>reading it — this asks GitHub and Fly, so it takes a moment</Note>}

      {data && (
        <>
          <Card
            title="Verdict"
            tone={data.needs_attention ? 'bad' : 'ok'}
            right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
          >
            <Note>{data.headline}</Note>
            {(data.fixed ?? []).map((f) => (
              <Note key={f}>fixed: {f}</Note>
            ))}
          </Card>

          {data.deployables.map((d) => (
            <Deployable key={d.name} d={d} />
          ))}

          {fleet && (
            <Card
              title="CI runners"
              tone={fleet.problem ? 'bad' : 'ok'}
              right={<Pill tone={fleet.problem ? 'bad' : 'ok'}>{fleet.queued.length} queued</Pill>}
            >
              <Note>
                Every deploy waits on these. A stopped machine does not fail anything — the run
                just says queued, which is what hid the twelve-hour delay this page was built for.
              </Note>
              {fleet.problem && <Problem>{fleet.problem}</Problem>}
              {fleet.machines.length === 0 ? (
                <Empty>{fleet.error ?? 'no machines reported'}</Empty>
              ) : (
                <table className="w-full text-sm mt-2">
                  <tbody>
                    {fleet.machines.map((m) => (
                      <tr key={m.id} className="border-b border-border last:border-0">
                        <td className="py-2 pr-3">
                          <Pill tone={m.state === 'started' ? 'ok' : 'bad'}>{m.state}</Pill>
                        </td>
                        <td className="py-2 pr-3 font-mono text-xs">{m.id}</td>
                        <td className="py-2 text-subtle">{m.region}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {fleet.queued.length > 0 && (
                <Scroll>
                  <table className="w-full text-sm mt-2">
                    <tbody>
                      {fleet.queued.map((q) => (
                        <tr key={q.url} className="border-b border-border last:border-0">
                          <td className="py-1 pr-3">{q.workflow}</td>
                          <td className="py-1 text-subtle">
                            <a href={q.url} className="underline" target="_blank" rel="noreferrer">
                              waiting
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Scroll>
              )}
            </Card>
          )}
        </>
      )}
    </Shell>
  );
}
