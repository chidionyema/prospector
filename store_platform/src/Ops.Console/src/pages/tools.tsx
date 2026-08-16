/**
 * Tools — every operator CLI in the repo, and which screen replaces it.
 *
 * This is the inventory the brief asked for: the proof that the console was built on top of the
 * tools that already exist rather than reinventing them. It is a hand-written table in
 * `prospector/ops/console_api.py` (`TOOLS`), not a directory scan, for one reason: a scan can say
 * a file exists but cannot say what it does to your data. `exists` IS measured on disk, so a tool
 * that gets deleted or renamed shows up here as missing instead of quietly staying in the list.
 *
 * Nothing on this page runs. The console executes exactly one command —
 * `python -m prospector.ops.console_api` — and every write goes through that gateway's confirm
 * step. A button that shells out to an arbitrary repo script would be a second, unguarded door.
 * The command is shown so it can be copied into a terminal.
 */
import { useMemo, useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Pill, Problem, Row, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Tool = {
  path: string;
  purpose: string;
  writes: boolean;
  screen: string;
  run: boolean;
  danger: string | null;
  command: string;
  exists: boolean;
};

type ToolsView = { root: string; tools: Tool[]; note: string };

const SCREEN_NAME: Record<string, string> = {
  '/': 'Now',
  '/engine': 'Engine',
  '/config': 'Settings',
  '/queue': 'Queue',
  '/runs': 'Runs',
  '/spend': 'Spend',
  '/metrics': 'Yield',
  '/catalogue': 'Shelf',
  '/tools': 'Tools (this page — no screen replaces it)',
  '/audit': 'Audit',
};

export default function Tools() {
  const { data, envelope, error } = useOps<ToolsView>('tools');
  const [q, setQ] = useState('');
  const [onlyWrites, setOnlyWrites] = useState(false);

  const groups = useMemo(() => {
    const rows = (data?.tools ?? []).filter((t) => {
      if (onlyWrites && !t.writes) return false;
      const needle = q.trim().toLowerCase();
      if (!needle) return true;
      return [t.path, t.purpose, t.command, t.screen]
        .join(' ')
        .toLowerCase()
        .includes(needle);
    });
    const by = new Map<string, Tool[]>();
    for (const t of rows) {
      const key = t.screen;
      if (!by.has(key)) by.set(key, []);
      by.get(key)!.push(t);
    }
    return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [data, q, onlyWrites]);

  const missing = (data?.tools ?? []).filter((t) => !t.exists);

  return (
    <Shell title="Tools" intro="Every operator command in the repo, and where it lives here.">
      {error ? <Problem>{error}</Problem> : null}
      {!data ? (
        <Card>
          <Spinner what="reading the tool table" />
        </Card>
      ) : null}

      {data ? (
        <Card title="Inventory" right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}>
          <Row label="Tools listed">{data.tools.length}</Row>
          <Row label="That write">{data.tools.filter((t) => t.writes).length}</Row>
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
            The table names them and the file is gone. Either the tool was deleted and this table
            is stale, or the checkout is incomplete.
          </p>
          {missing.map((t) => (
            <div key={t.path} className="wrap-any mt-1 font-mono text-[12px]">
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
            {screen === '/tools'
              ? 'Run these in a terminal. Nothing here is exposed as a button.'
              : `Covered by ${screen} in this console.`}
          </div>
          <div className="mt-2 flex flex-col gap-3">
            {tools.map((t) => (
              <div key={t.path + t.purpose} className="rounded-sm border border-border px-3 py-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[14px] font-[520]">{t.purpose}</span>
                  <div className="flex shrink-0 gap-1.5">
                    {t.writes ? <Pill tone="warn">writes</Pill> : <Pill tone="mute">reads</Pill>}
                    {t.exists ? null : <Pill tone="bad">missing</Pill>}
                  </div>
                </div>
                <div className="wrap-any mt-1 font-mono text-[11px] text-subtle">{t.path}</div>
                <pre className="scroll-x mt-2 rounded-sm bg-surface3 px-2 py-1.5 font-mono text-[11px]">
                  {t.command}
                </pre>
                {t.danger ? (
                  <div className="mt-1 text-[12px] text-bad-strong">care: {t.danger}</div>
                ) : null}
              </div>
            ))}
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
