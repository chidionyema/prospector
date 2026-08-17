/**
 * Method — how the agents are working, and whether it is getting better.
 *
 * Why this page exists. Of 373 complaints mined from every session transcript on this machine,
 * 110 are the founder unable to see the state without asking: "hours later i dont even know wat
 * you are working on and if it is done", "is anything passing? has pricing been fied and
 * deployed". Answering those in prose is what produced them. This page answers them with a
 * number that a scheduled job writes.
 *
 * The number is the founder-stop rate: how often he interrupts or refuses a tool call, per 100
 * calls. It is not a judgement about who was right. A stop means he wanted something different,
 * and a signature that recurs 20 times is a behaviour worth refusing before it runs.
 *
 * Every row carries the command that reads it. A row with no command is not being tracked by
 * anything, and the page says so rather than leaving the gap invisible.
 */
import Shell from '@/components/Shell';
import { AsOf, Card, Note, Pill, Problem, Row, Scroll, Stat } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Theme = {
  theme: string;
  count: number;
  months: number;
  by_month: Record<string, number>;
  check: string | null;
  enforced_by: string | null;
  enforced_live: boolean;
  tracked: boolean;
  samples: { month: string; text: string }[];
};

type MethodView = {
  present: boolean;
  note?: string;
  generator?: string;
  generated_at?: string;
  age_hours?: number;
  stale?: boolean;
  stale_note?: string;
  headline?: {
    stop_rate_per_100: number;
    target_30d: number;
    target_60d: number;
    verdict: string;
    complaints: number;
    messages: number;
    untracked_themes: number;
    unenforced_themes: number;
    inert_mechanisms: number;
    orphaned_mechanisms: number;
    output_tokens_per_call: number | null;
  };
  efficiency?: {
    unit: string;
    note: string;
    by_month: { month: string; output_tokens: number; tool_calls: number; per_call: number | null }[];
  };
  predictions?: {
    id: string;
    made_on: string;
    claim: string;
    metric: string;
    baseline: number;
    target: number;
    due: string;
    actual: number | null;
    verdict: string;
    moved?: number;
    if_wrong: string;
  }[];
  stops?: {
    events: number;
    calls: number;
    by_month: { month: string; stops: number; calls: number; rate: number | null }[];
    top_signatures: { signature: string; count: number; share: number }[];
  };
  themes?: Theme[];
  mechanisms?: { name: string; live: boolean }[];
};

export default function Method() {
  const { data, envelope, error } = useOps<MethodView>('method', {}, { pollMs: 300_000 });

  if (error) {
    return (
      <Shell title="Method">
        <Problem>{error}</Problem>
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell title="Method">
        <Card>reading the scoreboard…</Card>
      </Shell>
    );
  }
  if (!data.present) {
    return (
      <Shell title="Method" intro="How the agents are working, and whether it is getting better.">
        <Card title="No scoreboard yet">
          <Note>{data.note}</Note>
          <div className="mt-2 font-mono text-[12px] text-subtle">{data.generator}</div>
        </Card>
      </Shell>
    );
  }

  const h = data.headline!;
  const onTarget = h.stop_rate_per_100 <= h.target_30d;

  return (
    <Shell
      title="Method"
      intro="How the agents are working, and whether it is getting better. Mined from every session transcript on this machine."
    >
      {data.stale ? <Problem>{data.stale_note}</Problem> : null}

      <Card
        title="The number"
        right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
      >
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat
            label="stops per 100 calls"
            value={h.stop_rate_per_100}
            note="how often he had to interrupt"
            tone={onTarget ? 'ok' : 'warn'}
          />
          <Stat label="target, 30 days" value={h.target_30d} note="below this or the rules were wrong" />
          <Stat label="target, 60 days" value={h.target_60d} note="the second gate" />
          <Stat
            label="complaints"
            value={h.complaints}
            note={`of ${h.messages} messages he typed`}
          />
        </div>
        <div className="mt-4">
          <Row label="Verdict">{h.verdict}</Row>
          <Row label="Themes nothing tracks">{h.untracked_themes}</Row>
          <Row label="Themes nothing can refuse">{h.unenforced_themes}</Row>
          <Row label="Scripts nothing invokes">{h.inert_mechanisms}</Row>
          <Row label="Scoreboard age">{data.age_hours}h</Row>
        </div>
        <Note>
          If this rate does not fall, the rules were wrong and get deleted, not defended. That is
          the whole test.
        </Note>
      </Card>

      {data.predictions?.length ? (
        <Card title="Predictions, and whether they were right">
          <Note>
            Every rule names the number it should move, the target, and the date it gets graded.
            A prediction written after the fact cannot catch the case where the number improved
            for unrelated reasons and the fix took the credit.
          </Note>
          <div className="mt-3 flex flex-col gap-3">
            {data.predictions.map((p) => (
              <div key={p.id} className="border-t border-border pt-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-mono text-[13px]">{p.id}</span>
                  <Pill
                    tone={
                      p.verdict === 'hit' ? 'ok' : p.verdict === 'missed' ? 'bad' : 'mute'
                    }
                  >
                    {p.verdict}
                  </Pill>
                </div>
                <div className="mt-1 text-[13px]">{p.claim}</div>
                <div className="mt-1 font-mono text-[11px] text-subtle">
                  {p.metric}: {p.baseline} → target {p.target} · now {p.actual ?? '—'} · due {p.due}
                </div>
                <div className="mt-1 text-[12px] text-muted">If wrong: {p.if_wrong}</div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {data.efficiency?.by_month?.length ? (
        <Card title="Tokens per move">
          <Note>
            Fewest tokens for the job, without hurting quality or speed. The ratio, not the
            total — a raw total falls in a quiet month, which would reward doing less rather
            than doing it in fewer moves.
          </Note>
          <Scroll>
            <table className="mt-2 w-full text-[13px]">
              <thead className="text-subtle">
                <tr>
                  <th className="py-1 text-left font-[520]">month</th>
                  <th className="py-1 text-right font-[520]">output tokens</th>
                  <th className="py-1 text-right font-[520]">tool calls</th>
                  <th className="py-1 text-right font-[520]">per call</th>
                </tr>
              </thead>
              <tbody>
                {data.efficiency.by_month.map((m) => (
                  <tr key={m.month} className="border-t border-border">
                    <td className="py-1.5 font-mono">{m.month}</td>
                    <td className="py-1.5 text-right">{m.output_tokens.toLocaleString()}</td>
                    <td className="py-1.5 text-right">{m.tool_calls.toLocaleString()}</td>
                    <td className="py-1.5 text-right font-[560]">{m.per_call ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <Note>{data.efficiency.note}</Note>
        </Card>
      ) : null}

      {data.stops?.by_month?.length ? (
        <Card title="By month">
          <Scroll>
            <table className="w-full text-[13px]">
              <thead className="text-subtle">
                <tr>
                  <th className="py-1 text-left font-[520]">month</th>
                  <th className="py-1 text-right font-[520]">stops</th>
                  <th className="py-1 text-right font-[520]">calls</th>
                  <th className="py-1 text-right font-[520]">per 100</th>
                </tr>
              </thead>
              <tbody>
                {data.stops.by_month.map((m) => (
                  <tr key={m.month} className="border-t border-border">
                    <td className="py-1.5 font-mono">{m.month}</td>
                    <td className="py-1.5 text-right">{m.stops}</td>
                    <td className="py-1.5 text-right">{m.calls}</td>
                    <td className="py-1.5 text-right font-[560]">{m.rate ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        </Card>
      ) : null}

      {data.themes?.length ? (
        <Card title="What he complains about, clustered">
          <Note>
            Each row is a complaint made more than once. `check` is the command that reads its
            number. A row with no check is not tracked by anything.
          </Note>
          <div className="mt-3 flex flex-col gap-3">
            {data.themes.map((t) => (
              <div key={t.theme} className="border-t border-border pt-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[14px] font-[560]">{t.theme}</span>
                  <span className="font-mono text-[13px]">{t.count}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <Pill tone={t.tracked ? 'ok' : 'bad'}>{t.tracked ? 'tracked' : 'untracked'}</Pill>
                  <Pill tone={t.enforced_live ? 'ok' : 'mute'}>
                    {t.enforced_live ? 'rule is live' : 'nothing refuses it'}
                  </Pill>
                  <Pill tone="mute">{t.months} month{t.months === 1 ? '' : 's'}</Pill>
                </div>
                {t.check ? (
                  <div className="mt-1.5 font-mono text-[11px] text-subtle">{t.check}</div>
                ) : null}
                {t.enforced_by ? (
                  <div className="mt-1 text-[12px] text-muted">{t.enforced_by}</div>
                ) : null}
                {t.samples?.length ? (
                  <div className="mt-2 text-[12px] text-muted">
                    {t.samples.slice(-1).map((s) => (
                      <div key={s.text}>
                        <span className="text-subtle">[{s.month}]</span> {s.text}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {data.stops?.top_signatures?.length ? (
        <Card title="What was running when he stopped it">
          <Scroll>
            <table className="w-full text-[13px]">
              <tbody>
                {data.stops.top_signatures.map((s) => (
                  <tr key={s.signature} className="border-t border-border">
                    <td className="py-1.5 font-mono">{s.signature}</td>
                    <td className="py-1.5 text-right">{s.count}</td>
                    <td className="py-1.5 text-right text-subtle">{s.share}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        </Card>
      ) : null}

      {data.mechanisms?.length ? (
        <Card title="Safeguards, and whether anything invokes them">
          <Note>
            A script nothing calls is not a safeguard, it is a file. This is read from
            settings.json and the launchd agents, not from a list somebody maintained.
          </Note>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {data.mechanisms.map((m) => (
              <Pill key={m.name} tone={m.live ? 'ok' : 'bad'}>
                {m.name}
              </Pill>
            ))}
          </div>
        </Card>
      ) : null}
    </Shell>
  );
}
