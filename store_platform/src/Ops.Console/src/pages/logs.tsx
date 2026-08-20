/**
 * Logs — every service's lines in one place.
 *
 * Why this page exists. Founder, 2026-08-19: "right now we dont have proper loggin visibility in
 * store fonrt, engine adin etc we log but no cetral place to view". Before it, answering "what
 * happened to this buyer" meant `fly logs` against three apps in three terminals, each holding
 * roughly four minutes of history on a busy daemon, none of them joinable to the others. The
 * design is `docs/LOGGING_AND_RETENTION.md` Part 4; this screen is step 10 of its plan.
 *
 * The correlation id is what makes it a console rather than a viewer. Every line a purchase
 * touched carries the same `corr`, from the browser that opened the checkout through Stripe's
 * metadata to the fulfilment line, so clicking one is the whole trail across four services.
 *
 * THE FAILURE THIS PAGE IS BUILT TO AVOID is its own empty state. A dispatcher answering from a
 * checkout that is not the engine resolves a log directory production never writes to, finds
 * nothing, and renders a table that looks exactly like a healthy quiet estate. So every bound the
 * search applied is displayed, and "no directory" is a different message from "no matches".
 */
import { useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Scroll, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type LogRow = {
  ts?: string;
  svc?: string;
  lvl?: string;
  evt?: string;
  msg?: string;
  corr?: string;
  host?: string;
  ctx?: Record<string, unknown>;
};

type LogsView = {
  dir: string;
  present: boolean;
  host: string;
  rows: LogRow[];
  matched: number;
  scanned: number;
  unreadable: number;
  files_read: number;
  files_total: number;
  files_capped: boolean;
  truncated: boolean;
  days: string[];
  services: string[];
  levels: string[];
  limit: number;
};

/** A filter set the operator has committed to. Held apart from what they are typing. */
type Filters = {
  service: string;
  level: string;
  corr: string;
  q: string;
  limit: string;
};

const EMPTY: Filters = { service: '', level: '', corr: '', q: '', limit: '200' };

function levelTone(lvl?: string): 'ok' | 'warn' | 'bad' | 'mute' | 'plain' {
  if (lvl === 'crit' || lvl === 'error') return 'bad';
  if (lvl === 'warn') return 'warn';
  if (lvl === 'debug') return 'mute';
  return 'plain';
}

/** `2026-08-19T22:41:07.481Z` to `22:41:07`, with the date only when it is not today's rows. */
function clock(ts?: string): string {
  if (!ts || ts.length < 20) return ts ?? '';
  return ts.slice(11, 19);
}

function day(ts?: string): string {
  return ts && ts.length >= 10 ? ts.slice(0, 10) : '';
}

const SELECT =
  'tap rounded-sm border border-border-control bg-surface px-2 text-[14px] text-text';
const INPUT = `${SELECT} min-w-0 flex-1`;

export default function LogsPage() {
  // What the operator is typing, and what they have committed to. Splitting the two is what
  // stops every keystroke spawning a Python process on the engine.
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [open, setOpen] = useState<number | null>(null);

  const { data, envelope, error, loading, refresh } = useOps<LogsView>('logs', {
    service: applied.service || undefined,
    level: applied.level || undefined,
    corr: applied.corr || undefined,
    q: applied.q || undefined,
    limit: applied.limit || undefined,
  });

  /** Show me everything this one purchase touched. The reason the page exists. */
  function traceCorrelation(corr: string) {
    const next = { ...EMPTY, corr, limit: applied.limit };
    setDraft(next);
    setApplied(next);
    setOpen(null);
  }

  const rows = data?.rows ?? [];
  const multiDay = new Set(rows.map((r) => day(r.ts))).size > 1;

  return (
    <Shell
      title="Logs"
      intro="Every service's lines in one place. Click a correlation id to follow one purchase across all of them."
    >
      <Card
        title="Filter"
        right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
      >
        <form
          className="flex flex-wrap items-stretch gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(draft);
            setOpen(null);
          }}
        >
          <select
            aria-label="Service"
            className={SELECT}
            value={draft.service}
            onChange={(e) => setDraft({ ...draft, service: e.target.value })}
          >
            <option value="">every service</option>
            {(data?.services ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            aria-label="Minimum level"
            className={SELECT}
            value={draft.level}
            onChange={(e) => setDraft({ ...draft, level: e.target.value })}
          >
            <option value="">every level</option>
            {(data?.levels ?? []).map((l) => (
              <option key={l} value={l}>
                {l} and worse
              </option>
            ))}
          </select>
          <input
            aria-label="Correlation id"
            className={INPUT}
            placeholder="correlation id"
            value={draft.corr}
            onChange={(e) => setDraft({ ...draft, corr: e.target.value })}
          />
          <input
            aria-label="Search text"
            className={INPUT}
            placeholder="text in any field"
            value={draft.q}
            onChange={(e) => setDraft({ ...draft, q: e.target.value })}
          />
          <button
            type="submit"
            className="tap rounded-sm border border-action bg-action px-3 text-[14px] font-[520] text-on-action"
          >
            Search
          </button>
          <button
            type="button"
            className="tap rounded-sm border border-border-control bg-surface px-3 text-[14px] font-[520] text-text"
            onClick={() => {
              setDraft(EMPTY);
              setApplied(EMPTY);
              setOpen(null);
            }}
          >
            Clear
          </button>
        </form>
      </Card>

      {error ? <Problem>{error}</Problem> : null}

      {/*
        The directory being absent is NOT an empty log. It means this dispatcher is answering
        from a machine that does not hold the volume, and every row below would be missing for a
        reason that has nothing to do with the estate being quiet.
      */}
      {data && !data.present ? (
        <Problem>
          No log directory on <code>{data.host}</code>: <code>{data.dir}</code> does not exist.
          The central log lives on the engine machine, so a console answering from anywhere else
          has nothing to read. This is not an empty log.
        </Problem>
      ) : null}

      <Card
        title="Lines"
        right={
          <span className="font-mono text-[12px] text-subtle">
            {data ? `${data.matched} matched of ${data.scanned} scanned` : ''}
          </span>
        }
      >
        {loading && !data ? <Spinner what="logs" /> : null}

        {data && data.present ? (
          <p className="mb-2 font-mono text-[12px] text-subtle">
            {data.host} · {data.dir} · {data.files_read} of {data.files_total} day files
            {data.days.length ? ` · ${data.days[data.days.length - 1]} to ${data.days[0]}` : ''}
          </p>
        ) : null}

        {/*
          Every bound the search applied, said out loud. A reader who cannot tell "nothing
          matched" from "we stopped looking" will read a bounded search as a quiet system, which
          is the whole class of failure this programme exists to remove.
        */}
        {data?.truncated ? (
          <Note>
            A day file was longer than the read window, so these are its most recent lines only.
            Narrow by service or search text to see further back.
          </Note>
        ) : null}
        {data?.files_capped ? (
          <Note>
            More day files exist than one search opens; the newest were read. Filter by service to
            reach older days.
          </Note>
        ) : null}
        {data && data.matched > rows.length ? (
          <Note>
            {data.matched} lines matched and the newest {rows.length} are shown. Raise the limit or
            narrow the filter.
          </Note>
        ) : null}
        {data && data.unreadable > 0 ? (
          <Note>
            {data.unreadable} line{data.unreadable === 1 ? '' : 's'} would not parse and were
            skipped. A torn last line is normal while a service is writing.
          </Note>
        ) : null}

        {data && data.present && rows.length === 0 ? (
          <Empty>
            Nothing matched. {data.files_total === 0 ? 'No service has shipped a line yet.' : ''}
          </Empty>
        ) : null}

        {rows.length ? (
          <Scroll>
            <ul className="m-0 list-none p-0">
              {rows.map((r, i) => (
                <li key={`${r.ts}-${i}`} className="border-b border-border py-1.5 last:border-0">
                  <button
                    type="button"
                    className="flex w-full items-baseline gap-2 text-left"
                    onClick={() => setOpen(open === i ? null : i)}
                  >
                    <span className="font-mono text-[12px] tabular-nums text-subtle">
                      {multiDay ? `${day(r.ts)} ` : ''}
                      {clock(r.ts)}
                    </span>
                    <Pill tone={levelTone(r.lvl)}>{r.lvl ?? 'info'}</Pill>
                    <span className="font-mono text-[12px] text-muted">{r.svc}</span>
                    <span className="font-mono text-[13px] text-text">{r.evt}</span>
                    <span className="min-w-0 flex-1 truncate text-[13px] text-muted">{r.msg}</span>
                  </button>
                  {open === i ? (
                    <div className="mt-1 pl-2">
                      {r.msg ? (
                        <p className="wrap-any mb-1 text-[13px] leading-[1.6] text-text">{r.msg}</p>
                      ) : null}
                      {r.ctx && Object.keys(r.ctx).length ? (
                        <pre className="wrap-any m-0 rounded-sm bg-surface2 px-2 py-1 font-mono text-[12px] text-muted">
                          {JSON.stringify(r.ctx, null, 2)}
                        </pre>
                      ) : null}
                      <p className="mb-0 mt-1 font-mono text-[12px] text-subtle">
                        {r.ts}
                        {r.host ? ` · ${r.host}` : ''}
                        {r.corr ? ' · ' : ''}
                        {r.corr ? (
                          <button
                            type="button"
                            className="underline underline-offset-2"
                            onClick={() => traceCorrelation(r.corr as string)}
                          >
                            trace {r.corr}
                          </button>
                        ) : null}
                      </p>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </Scroll>
        ) : null}

        <p className="mb-0 mt-3 text-[13px]">
          <button type="button" className="underline underline-offset-2" onClick={refresh}>
            Re-read now
          </button>
        </p>
      </Card>
    </Shell>
  );
}
