/**
 * Settings — every engine knob, editable, grouped by what it does.
 *
 * Founder requirement: "all this needs to be configurable from the admin portal", and "an
 * operator should be able to find 'how many ideas per batch' without knowing it is called
 * batch_size". So the groups are named for the job, the YAML path is shown small and second, and
 * the search box matches the label as well as the path.
 *
 * The writer is `prospector/ops/yaml_surgery.py`, always, through
 * `config_editor.write_config`. There is no second path. `yaml.safe_dump` on this file measured
 * 2034 lines in and 981 out — 1173 comment lines destroyed, including founder directives and
 * calibration receipts — which is why a knob the surgeon cannot locate is shown READ ONLY with
 * the refusal reason instead of being written by something else.
 *
 * Writability is MEASURED, not declared: the gateway runs the real rewriter over every knob and
 * reports what it actually refused. A UI that offered a save the writer then refused would read
 * to the operator as a broken button.
 */
import { useMemo, useState } from 'react';

import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Card, Note, Pill, Problem, Row, Scroll } from '@/components/ui';
import { ago, clock } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Knob = {
  key: string;
  path: string[];
  group: string;
  label: string;
  kind: 'int' | 'float' | 'bool' | 'list' | 'str';
  min?: number;
  max?: number;
  choices?: string[];
  help: string;
  current: unknown;
  present: boolean;
  moat_affecting: boolean;
  high_blast?: boolean;
  writable: boolean;
  reason: string | null;
};
type Group = { group: string; blurb: string; knobs: Knob[] };
type ConfigView = {
  path: string;
  readable: boolean;
  mtime: number;
  hash: string;
  lines: number;
  groups: Group[];
  certification: { certified?: boolean; [k: string]: unknown };
  history: { backup: string; hash: string; moat_affecting: boolean; ts: string }[];
  backups: { filename?: string; name?: string; ts?: string; size?: number }[];
  writer: string;
  writer_note: string;
};
type Intent = Record<string, unknown>;

const GROUP_TITLE: Record<string, string> = {
  work: 'How much work it takes on',
  evidence: 'How it searches for evidence',
  brains: 'Which brains it uses',
  speed: 'How hard it pushes them',
  money: 'What it may spend',
};

export default function ConfigPage() {
  const cfg = useOps<ConfigView>('config');
  const intents = useOps<{ rows: Intent[] }>('intents', { limit: 50 });
  const [q, setQ] = useState('');

  // `?? []` is a fresh array on every render, so the memo below never hit its cache and the whole
  // knob list was re-filtered on every keystroke. Memo the fallback and the memo starts working.
  const groups = useMemo(() => cfg.data?.groups ?? [], [cfg.data]);
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return groups;
    return groups
      .map((g) => ({
        ...g,
        knobs: g.knobs.filter(
          (k) =>
            k.label.toLowerCase().includes(needle) ||
            k.key.toLowerCase().includes(needle) ||
            k.help.toLowerCase().includes(needle),
        ),
      }))
      .filter((g) => g.knobs.length > 0);
  }, [groups, q]);

  const unwritable = groups.flatMap((g) => g.knobs.filter((k) => !k.writable));

  return (
    <Shell title="Settings" intro="Every engine knob, grouped by what it does.">
      {cfg.error ? <Problem>{cfg.error}</Problem> : null}

      <Card
        title="The file"
        right={<AsOf asOf={cfg.envelope?.as_of} tookMs={cfg.envelope?.took_ms} />}
      >
        {cfg.data ? (
          <>
            <Row label="Path">{cfg.data.path}</Row>
            <Row label="Size">{cfg.data.lines} lines</Row>
            <Row label="Last changed">
              {clock(new Date(cfg.data.mtime * 1000).toISOString())} ·{' '}
              {ago(new Date(cfg.data.mtime * 1000).toISOString())}
            </Row>
            <Row label="Fingerprint">{cfg.data.hash}</Row>
            <Row label="Golden-set certification">
              <Pill tone={cfg.data.certification?.certified ? 'ok' : 'warn'}>
                {cfg.data.certification?.certified ? 'certified' : 'not certified'}
              </Pill>
            </Row>
            <Row label="Written by">{cfg.data.writer}</Row>
            <div className="mt-3">
              <Note>{cfg.data.writer_note}</Note>
            </div>
          </>
        ) : (
          <div className="text-[13px] text-subtle">reading config.yaml…</div>
        )}
      </Card>

      {unwritable.length ? (
        <Card title={`${unwritable.length} knob(s) cannot be edited here`} tone="warn">
          <p className="text-[13px] text-text">
            The comment-preserving rewriter could not find a single scalar line for these, so this
            console will not write them. Nothing falls back to a serialiser — that is the
            destruction the rewriter exists to prevent. Edit them at a terminal, or convert the
            block they live in to plain <span className="font-mono">key: value</span> lines.
          </p>
          <div className="mt-3 flex flex-col gap-2">
            {unwritable.map((k) => (
              <div key={k.key} className="rounded-sm border border-border bg-surface2 px-3 py-2">
                <div className="text-[13px] font-[520]">{k.label}</div>
                <div className="font-mono text-[12px] text-subtle">{k.key}</div>
                <div className="wrap-any mt-1 text-[12px] text-muted">{k.reason}</div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <div>
        <label className="text-[12px] text-muted" htmlFor="find">
          Find a setting
        </label>
        <input
          id="find"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="ideas per batch, spend, search chain…"
          className="tap mt-1 w-full rounded-sm border border-border-control bg-surface px-3 text-[16px]"
        />
      </div>

      {filtered.map((g) => (
        <Card key={g.group} title={GROUP_TITLE[g.group] ?? g.group}>
          <p className="text-[13px] text-muted">{g.blurb}</p>
          <div className="mt-3 flex flex-col gap-4">
            {g.knobs.map((k) => (
              <KnobEditor
                key={k.key}
                knob={k}
                mtime={cfg.data?.mtime ?? 0}
                onDone={() => {
                  cfg.refresh();
                  intents.refresh();
                }}
              />
            ))}
          </div>
        </Card>
      ))}

      <Card title="What changed, and who changed it">
        <p className="text-[13px] text-muted">
          Two records, because they answer different halves. The console&apos;s audit log carries
          the person and the reason; config.yaml&apos;s own history carries the backup file each
          save left behind.
        </p>

        <h3 className="mt-4 text-[13px] font-[560]">From this console</h3>
        {(intents.data?.rows ?? []).filter(isConfigIntent).length === 0 ? (
          <div className="py-2 text-[13px] text-subtle">no config change recorded yet</div>
        ) : (
          <Scroll>
            <table className="w-full min-w-[560px] border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-border text-left text-[12px] uppercase tracking-[0.06em] text-subtle">
                  <th className="py-2 pr-3 font-[520]">when</th>
                  <th className="py-2 pr-3 font-[520]">who</th>
                  <th className="py-2 pr-3 font-[520]">key</th>
                  <th className="py-2 pr-3 font-[520]">change</th>
                  <th className="py-2 font-[520]">why</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {(intents.data?.rows ?? []).filter(isConfigIntent).map((e, i) => (
                  <tr key={`${String(e.ts)}-${i}`} className="border-b border-border align-top">
                    <td className="py-2 pr-3 whitespace-nowrap">
                      {clock(String(e.ts))}
                      <div className="text-[11px] text-subtle">{ago(String(e.ts))}</div>
                    </td>
                    <td className="py-2 pr-3">{String(e.actor ?? '—')}</td>
                    <td className="wrap-any py-2 pr-3">{String(e.key ?? '—')}</td>
                    <td className="wrap-any py-2 pr-3">
                      {e.applied === false ? (
                        <span className="text-bad-strong">refused: {String(e.refused ?? '')}</span>
                      ) : (
                        `${JSON.stringify(e.before)} → ${JSON.stringify(e.after)}`
                      )}
                    </td>
                    <td className="wrap-any py-2 text-[12px]">{String(e.reason ?? '')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        )}

        <h3 className="mt-5 text-[13px] font-[560]">Backups the file itself kept</h3>
        {(cfg.data?.history ?? []).length === 0 ? (
          <div className="py-2 text-[13px] text-subtle">no save recorded</div>
        ) : (
          <div className="flex flex-col gap-2">
            {(cfg.data?.history ?? [])
              .slice()
              .reverse()
              .slice(0, 15)
              .map((h) => (
                <div key={`${h.ts}-${h.backup}`} className="rounded-sm border border-border px-3 py-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-mono text-[12px]">{clock(h.ts)}</span>
                    <span className="text-[12px] text-subtle">{ago(h.ts)}</span>
                  </div>
                  <div className="wrap-any font-mono text-[11px] text-subtle">{h.backup}</div>
                  {h.moat_affecting ? <Pill tone="warn">moat-affecting</Pill> : null}
                </div>
              ))}
          </div>
        )}

        <h3 className="mt-5 text-[13px] font-[560]">Restore a backup</h3>
        {(cfg.data?.backups ?? []).length === 0 ? (
          <div className="py-2 text-[13px] text-subtle">
            no backup file is present next to config.yaml
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {(cfg.data?.backups ?? []).slice(0, 10).map((b) => {
              const name = String(b.filename ?? b.name ?? '');
              return (
                <div key={name} className="rounded-sm border border-border px-3 py-2">
                  <div className="wrap-any font-mono text-[12px]">{name}</div>
                  <div className="mt-2">
                    <Confirm
                      action="config.restore"
                      kind="danger"
                      label="Restore this file"
                      applyLabel="Yes — overwrite config.yaml"
                      payload={() => ({ filename: name, nonce: nonce() })}
                      renderPreview={(p) => (
                        <div className="flex flex-col gap-1">
                          <div>
                            This replaces config.yaml with{' '}
                            <span className="font-mono">{name}</span>.
                          </div>
                          <div className="wrap-any text-[12px] text-muted">
                            {JSON.stringify(p)}
                          </div>
                        </div>
                      )}
                      onApplied={() => cfg.refresh()}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </Shell>
  );
}

function isConfigIntent(e: Intent): boolean {
  const a = String(e.actuator ?? '');
  return a.startsWith('engine.config') || a.startsWith('console.config');
}

function KnobEditor({
  knob,
  mtime,
  onDone,
}: {
  knob: Knob;
  mtime: number;
  onDone: () => void;
}) {
  const [value, setValue] = useState<string>(toInput(knob));
  const [reason, setReason] = useState('');
  const [ack, setAck] = useState(false);
  const dirty = value !== toInput(knob);

  return (
    <div
      className={`rounded-sm border px-3 py-3 ${
        knob.high_blast ? 'border-bad/40 bg-bad-bg' : knob.writable ? 'border-border' : 'border-warn/50 bg-warn-bg'
      }`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[14px] font-[560]">{knob.label}</div>
        <div className="flex flex-wrap gap-1">
          {knob.moat_affecting ? <Pill tone="warn">affects the moat</Pill> : null}
          {knob.high_blast ? <Pill tone="bad">decides who may rule</Pill> : null}
          {!knob.writable ? <Pill tone="warn">read only</Pill> : null}
        </div>
      </div>
      <div className="font-mono text-[11px] text-subtle">{knob.key}</div>
      <p className="mt-1 text-[13px] text-muted">{knob.help}</p>

      <div className="mt-2 text-[13px]">
        Now: <span className="font-mono">{JSON.stringify(knob.current)}</span>
      </div>

      {!knob.writable ? (
        <div className="wrap-any mt-2 text-[12px] text-warn-strong">{knob.reason}</div>
      ) : (
        <>
          <div className="mt-3">
            {knob.kind === 'bool' ? (
              <label className="flex items-center gap-2 text-[14px]">
                <input
                  type="checkbox"
                  className="h-5 w-5"
                  checked={value === 'true'}
                  onChange={(e) => setValue(e.target.checked ? 'true' : 'false')}
                />
                {value === 'true' ? 'on' : 'off'}
              </label>
            ) : (
              <input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                inputMode={knob.kind === 'int' || knob.kind === 'float' ? 'decimal' : 'text'}
                className="tap w-full rounded-sm border border-border-control bg-surface px-2 font-mono text-[16px]"
                aria-label={knob.label}
              />
            )}
            {knob.kind === 'list' ? (
              <div className="mt-1 text-[12px] text-subtle">
                Comma or space separated, in order.
                {knob.choices ? ` Allowed: ${knob.choices.join(', ')}` : ''}
              </div>
            ) : null}
            {knob.min !== undefined || knob.max !== undefined ? (
              <div className="mt-1 text-[12px] text-subtle">
                Range {knob.min ?? '−∞'} to {knob.max ?? '∞'}.
              </div>
            ) : null}
          </div>

          {dirty ? (
            <div className="mt-3 flex flex-col gap-2">
              <label className="text-[12px] text-muted" htmlFor={`why-${knob.key}`}>
                Why (required — a diff nobody can explain six weeks later is not a record)
              </label>
              <input
                id={`why-${knob.key}`}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="tap rounded-sm border border-border-control bg-surface px-2 text-[16px]"
              />

              {knob.high_blast ? (
                <label className="flex items-start gap-2 text-[13px]">
                  <input
                    type="checkbox"
                    checked={ack}
                    onChange={(e) => setAck(e.target.checked)}
                    className="mt-1 h-5 w-5"
                  />
                  <span>
                    I understand this decides which brain may rule a verdict, and therefore what
                    can reach the shelf.
                  </span>
                </label>
              ) : null}

              <Confirm
                action="config.set"
                kind={knob.high_blast ? 'danger' : 'primary'}
                label="Save this setting"
                disabled={!reason.trim() || (knob.high_blast && !ack)}
                payload={() => ({
                  key: knob.key,
                  value: fromInput(knob, value),
                  reason: reason.trim(),
                  mtime,
                  ...(knob.high_blast ? { acknowledge_moat: true } : {}),
                  nonce: nonce(),
                })}
                renderPreview={(p) => <ConfigPreview p={p} />}
                onApplied={onDone}
              />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

/** Everything the operator must see before a config save, in the order it matters. */
function ConfigPreview({ p }: { p: Record<string, unknown> }) {
  const diff = p.diff as unknown;
  return (
    <div className="flex flex-col gap-2">
      <div>
        <span className="font-mono">{String(p.key)}</span>:{' '}
        <span className="font-mono">{JSON.stringify(p.before)}</span> →{' '}
        <span className="font-mono">{JSON.stringify(p.after)}</span>
      </div>

      {p.unchanged ? <Note>That is already the value. Saving would change nothing.</Note> : null}

      {p.conflict ? <Problem>{String(p.conflict_note)}</Problem> : null}

      {p.writable === false ? (
        <Problem>Cannot be written: {String(p.not_writable_reason)}</Problem>
      ) : null}

      {p.valid === false ? (
        <Problem>
          The engine says this config would be invalid:{' '}
          {JSON.stringify(p.validation_errors)}
        </Problem>
      ) : null}

      {p.moat_affecting ? <Problem>{String(p.moat_note)}</Problem> : null}
      {p.high_blast ? <Problem>{String(p.high_blast_note)}</Problem> : null}

      <div>
        <div className="text-[12px] uppercase tracking-[0.06em] text-subtle">diff</div>
        <Scroll>
          <pre className="font-mono text-[11px] text-muted">
            {typeof diff === 'string' ? diff : JSON.stringify(diff, null, 1)}
          </pre>
        </Scroll>
      </div>

      <div className="text-[12px] text-muted">
        Written by {String(p.writer)} · takes effect: {String(p.takes_effect)}
      </div>
    </div>
  );
}

function toInput(k: Knob): string {
  if (k.kind === 'bool') return k.current ? 'true' : 'false';
  if (k.kind === 'list') return Array.isArray(k.current) ? (k.current as unknown[]).join(', ') : '';
  return k.current === null || k.current === undefined ? '' : String(k.current);
}

/**
 * The browser converts the string the operator typed into the JSON type the knob declares — and
 * nothing more. Range, choices and duplicate checks all happen in Python (`_coerce`), so a
 * caller that skips this page meets the same rules.
 */
function fromInput(k: Knob, v: string): unknown {
  if (k.kind === 'bool') return v === 'true';
  if (k.kind === 'list') {
    return v
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }
  // Before the `str` branch existed this fell through to parseFloat, so a model pin named "3"
  // was sent as the number 3 and written to config.yaml as an unquoted scalar.
  if (k.kind === 'str') return v.trim();
  if (k.kind === 'int') {
    const n = Number.parseInt(v, 10);
    return Number.isFinite(n) ? n : v;
  }
  const f = Number.parseFloat(v);
  return Number.isFinite(f) ? f : v;
}

function nonce(): string {
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
