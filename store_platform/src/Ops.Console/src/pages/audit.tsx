/**
 * Audit — every write this console attempted, newest first.
 *
 * Refusals are in here alongside the successes, and that is the point. A log that records only
 * what worked cannot answer "why did nothing publish yesterday" — the answer is usually a refusal
 * nobody saw. So `applied: false` rows are rendered as loudly as the rest.
 *
 * Rows are written by the gateway (`_record_intent`), append-only, and they carry the actor and
 * the reason the operator typed. Each actuator writes its own extra fields; rather than guess a
 * union type, the known fields are rendered and the remainder is shown verbatim.
 */
import { useMemo, useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Row, Spinner } from '@/components/ui';
import { ABSENT, ago, clock } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Intent = Record<string, unknown> & {
  ts?: string;
  actuator?: string;
  actor?: string;
  reason?: string;
  applied?: boolean;
  changed?: boolean;
  nonce?: string;
};

type IntentsView = {
  path: string;
  present: boolean;
  total: number;
  unreadable_lines: number;
  rows: Intent[];
};

const KNOWN = new Set(['ts', 'actuator', 'actor', 'reason', 'applied', 'changed', 'nonce']);

export default function Audit() {
  const [limit, setLimit] = useState(200);
  const { data, envelope, error } = useOps<IntentsView>('intents', { limit });
  const [q, setQ] = useState('');
  const [onlyRefused, setOnlyRefused] = useState(false);

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    const needle = q.trim().toLowerCase();
    return all.filter((r) => {
      if (onlyRefused && r.applied !== false) return false;
      if (!needle) return true;
      return JSON.stringify(r).toLowerCase().includes(needle);
    });
  }, [data, q, onlyRefused]);

  const refused = (data?.rows ?? []).filter((r) => r.applied === false).length;

  return (
    <Shell title="Audit" intro="Every write this console tried, and every one it refused.">
      {error ? <Problem>{error}</Problem> : null}
      {!data ? (
        <Card>
          <Spinner what="reading the intent log" />
        </Card>
      ) : null}

      {data ? (
        <Card title="The log" right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}>
          {!data.present ? (
            <Note>
              No intent log yet at <span className="font-mono">{data.path}</span>. That means no
              write has been made through this console — it is not a read failure.
            </Note>
          ) : (
            <>
              <Row label="Entries">{data.total}</Row>
              <Row label="Showing">
                newest {Math.min(limit, data.total)} of {data.total}
              </Row>
              <Row label="Refused">{refused}</Row>
              <Row label="File">
                <span className="wrap-any font-mono text-[11px]">{data.path}</span>
              </Row>
              {data.unreadable_lines > 0 ? (
                <Problem>
                  {data.unreadable_lines} line(s) in the log could not be parsed. A torn write
                  leaves a partial line; those entries are lost, not merely hidden.
                </Problem>
              ) : null}
            </>
          )}

          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="find an action, an id, a reason…"
            className="tap mt-3 w-full rounded-sm border border-border bg-surface px-3 text-[16px]"
          />
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={onlyRefused}
                onChange={(e) => setOnlyRefused(e.target.checked)}
                className="h-4 w-4"
              />
              only the refusals
            </label>
            {([200, 1000] as const).map((n) => (
              <button
                key={n}
                onClick={() => setLimit(n)}
                className={`tap rounded-sm border px-3 text-[13px] ${
                  n === limit
                    ? 'border-action bg-action text-on-action'
                    : 'border-border bg-surface text-muted'
                }`}
              >
                last {n}
              </button>
            ))}
          </div>
        </Card>
      ) : null}

      {data && rows.length === 0 ? (
        <Card>
          <Empty>
            {data.total === 0 ? 'Nothing has been written from this console.' : 'Nothing matches.'}
          </Empty>
        </Card>
      ) : null}

      {rows.map((r, i) => {
        const extra = Object.fromEntries(
          Object.entries(r).filter(([k, v]) => !KNOWN.has(k) && v !== null && v !== ''),
        );
        const tone = r.applied === false ? 'bad' : r.changed === false ? 'warn' : 'ok';
        return (
          <div
            key={`${r.ts ?? i}-${r.nonce ?? i}`}
            className={`rounded-md border bg-surface2 px-4 py-3 ${
              tone === 'bad' ? 'border-bad/50' : tone === 'warn' ? 'border-warn/50' : 'border-border'
            }`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-mono text-[13px] font-[520]">{r.actuator ?? 'unnamed'}</span>
              <Pill tone={tone}>
                {r.applied === false ? 'refused' : r.changed === false ? 'no change' : 'applied'}
              </Pill>
            </div>
            <div className="mt-1 text-[12px] text-subtle">
              {r.ts ? `${clock(r.ts)} · ${ago(r.ts)}` : ABSENT} · by {r.actor ?? ABSENT}
            </div>
            {r.reason ? <p className="mt-2 text-[13px]">{r.reason}</p> : null}
            {Object.keys(extra).length > 0 ? (
              <pre className="scroll-x mt-2 rounded-sm bg-surface3 px-2 py-1.5 font-mono text-[11px]">
                {JSON.stringify(extra, null, 1)}
              </pre>
            ) : null}
          </div>
        );
      })}
    </Shell>
  );
}
