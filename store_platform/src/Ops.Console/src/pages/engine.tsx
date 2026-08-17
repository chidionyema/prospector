/**
 * Engine — start, stop, and who rules a verdict.
 *
 * Everything here calls a mechanism that already existed. The three pause files under
 * `store/scheduler/` are the same files the scheduler reads; this page arms and disarms them
 * through `prospector.ops.pause`, which is the same code the CLI uses. Nothing here invents a
 * new stop.
 *
 * The three scopes are NOT three flavours of the same switch, and the page says so on each one,
 * because getting them confused is the difference between stopping a spend leak and stopping the
 * queue from ever emptying.
 */
import Link from 'next/link';
import { useState } from 'react';

import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Card, Note, Pill, Problem, Row, Scroll } from '@/components/ui';
import { ABSENT, ago, duration } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Scope = {
  scope: string;
  path: string;
  armed: boolean;
  armed_at: string | null;
  actor: string | null;
  reason: string | null;
  stops: string;
  keeps_running: string;
  reader: string;
  note: string;
};
type PauseView = { scopes: Scope[]; any_armed: boolean };
type Job = {
  label: string;
  role: string;
  what: string;
  loaded: boolean | null;
  pid: number | null;
  reason: string;
  plist: string;
  plist_exists: boolean;
  /** false for a job that runs on a schedule and writes no heartbeat, e.g. the daily backup. */
  heartbeat?: boolean;
  /** true when a tracked plist exists in deploy/, so Start can install a job never installed. */
  installable?: boolean;
  error?: string;
};
type Beat = {
  role: string;
  present: boolean;
  pid: number | null;
  phase: string | null;
  code: string | null;
  ts: string | null;
  age_s: number | null;
  stale: boolean;
  alive: boolean;
};
/** The `status` read returns all of these in one envelope, so one call feeds three cards. */
type StatusView = {
  pause?: PauseView;
  supervisor?: { jobs: Job[] };
  heartbeats?: Record<string, Beat>;
};
type Tier = {
  name: string;
  state: string;
  trusted_final: boolean;
  dead_until: string | null;
  dead_for_s: number | null;
  strikes: number | null;
  last_error: string | null;
  health_file: string;
  roles: { role: string; position: number }[];
};
type Providers = {
  tiers: Tier[];
  orphan_marks: { name: string; health_file: string; dead_until: string; expired: boolean }[];
  moat_blind: string;
  drain_blind: string;
  trusted_final: string[];
};
type Routing = {
  operator: string[];
  noncritical_operator: string[];
  moat_primary_declared: string[];
  trusted: string[];
  trusted_source: string;
  head: string;
  head_trusted: boolean;
  publishes: boolean;
  provisional_tiers: string[];
  buildable: string[];
  problems: string[];
  advisories: string[];
};

const SCOPE_TITLE: Record<string, string> = {
  all: 'Stop everything',
  generation: 'Stop inventing new ideas',
  consumer: 'Stop checking ideas',
};

const ROLE_TITLE: Record<string, string> = {
  producer: 'Idea generator',
  consumer: 'Idea checker',
  backup: 'Offsite backup',
};

export default function Engine() {
  const pause = useOps<PauseView>('status');
  const providers = useOps<Providers>('providers');
  const routing = useOps<Routing>('routing');

  const status = pause.data as unknown as StatusView | undefined;
  const scopes = status?.pause?.scopes ?? [];
  const jobs = status?.supervisor?.jobs ?? [];
  const beats = status?.heartbeats ?? {};

  return (
    <Shell title="Engine" intro="Start, stop, and which brain is allowed to rule.">
      {pause.error ? <Problem>{pause.error}</Problem> : null}

      <Card
        title="Processes"
        right={<AsOf asOf={pause.envelope?.as_of} tookMs={pause.envelope?.took_ms} />}
      >
        {jobs.length === 0 ? (
          <div className="text-[13px] text-subtle">asking launchctl…</div>
        ) : null}
        <div className="flex flex-col gap-4">
          {jobs.map((j) => (
            <ProcessCard key={j.label} job={j} beat={beats[j.role]} onDone={pause.refresh} />
          ))}
        </div>
        <Note>
          Two different questions. The heartbeat says the process was alive a moment ago. launchd
          says whether anything will start it again when it dies. A process can be beating now and
          still be unheld, which is how the engine stayed dead for hours on 16 August.
        </Note>
      </Card>

      <Card
        title="Stops"
        right={<AsOf asOf={pause.envelope?.as_of} tookMs={pause.envelope?.took_ms} />}
      >
        {scopes.length === 0 ? (
          <div className="text-[13px] text-subtle">reading the pause files…</div>
        ) : null}
        <div className="flex flex-col gap-4">
          {scopes.map((s) => (
            <PauseCard key={s.scope} s={s} onDone={pause.refresh} />
          ))}
        </div>
      </Card>

      <Card
        title="Brains and their health"
        right={<AsOf asOf={providers.envelope?.as_of} tookMs={providers.envelope?.took_ms} />}
      >
        {providers.error ? <Problem>{providers.error}</Problem> : null}
        {providers.data?.moat_blind ? (
          <Problem>Nothing can rule a verdict: {providers.data.moat_blind}</Problem>
        ) : null}
        {providers.data?.drain_blind ? (
          <Note>The queue cannot drain: {providers.data.drain_blind}</Note>
        ) : null}
        <Scroll>
          <table className="w-full min-w-[520px] border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-border text-left text-[12px] uppercase tracking-[0.06em] text-subtle">
                <th className="py-2 pr-3 font-[520]">tier</th>
                <th className="py-2 pr-3 font-[520]">state</th>
                <th className="py-2 pr-3 font-[520]">rules finally</th>
                <th className="py-2 pr-3 font-[520]">roles</th>
                <th className="py-2 font-[520]">last error</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {(providers.data?.tiers ?? []).map((t) => (
                <tr key={`${t.name}:${t.health_file}`} className="border-b border-border align-top">
                  <td className="py-2 pr-3">{t.name}</td>
                  <td className="py-2 pr-3">
                    <Pill tone={t.state === 'live' ? 'ok' : t.state === 'dead' ? 'bad' : 'warn'}>
                      {t.state}
                    </Pill>
                    {t.dead_for_s ? (
                      <div className="mt-1 text-[11px] text-subtle">
                        benched {duration(t.dead_for_s)}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3">{t.trusted_final ? 'yes' : 'no'}</td>
                  <td className="py-2 pr-3 text-[12px]">
                    {t.roles.map((r) => `${r.role}#${r.position}`).join(', ') || ABSENT}
                  </td>
                  <td className="wrap-any py-2 text-[11px] text-muted">{t.last_error || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
        {providers.data?.orphan_marks?.length ? (
          <Note>
            {providers.data.orphan_marks.length} health mark(s) name a tier no chain uses any more.
            They are harmless, but they are why a tier list read from the health file alone is
            longer than the roster.
          </Note>
        ) : null}
      </Card>

      <Card
        title="Who may rule a verdict"
        right={<AsOf asOf={routing.envelope?.as_of} tookMs={routing.envelope?.took_ms} />}
      >
        {routing.error ? <Problem>{routing.error}</Problem> : null}
        {routing.data ? (
          <>
            <Row label="Verdict chain (operator)">{routing.data.operator.join(' → ')}</Row>
            <Row label="Trusted to rule finally">
              {routing.data.moat_primary_declared.join(', ')}
            </Row>
            <Row label="Declared by">{routing.data.trusted_source}</Row>
            <Row label="Head of the chain">
              <Pill tone={routing.data.head_trusted ? 'ok' : 'warn'}>{routing.data.head}</Pill>
            </Row>
            <Row label="A pass from the head can publish">
              {routing.data.publishes ? 'yes' : 'no — it would be stamped provisional'}
            </Row>
            <Row label="Non-critical chain">{routing.data.noncritical_operator.join(' → ')}</Row>
            {routing.data.problems.map((p) => (
              <Problem key={p}>{p}</Problem>
            ))}
            {routing.data.advisories.map((a) => (
              <Note key={a}>{a}</Note>
            ))}
            <div className="mt-4">
              <RosterEditor routing={routing.data} onDone={routing.refresh} />
            </div>
          </>
        ) : null}
      </Card>

      <Note>
        Wave size, spend cap, retrieval chain and the rest of the knobs live under{' '}
        <Link className="underline" href="/config">
          Settings
        </Link>
        . They are config.yaml edits, not runtime switches, so they take effect on the next tick.
      </Note>
    </Shell>
  );
}

/**
 * One engine process: whether launchd holds it, whether it is beating, and a Restart button.
 *
 * The two facts are separate on purpose. `loaded` is tri-state — true, false, or null for "could
 * not ask launchctl" — and null is rendered as unknown, not as a fault, because a box with no
 * launchctl is not a broken daemon.
 */
function ProcessCard({ job, beat, onDone }: { job: Job; beat?: Beat; onDone: () => void }) {
  const held = job.loaded === true;
  const unheld = job.loaded === false;
  const beating = beat?.present === true && beat.stale === false;
  // A scheduled job writes no heartbeat and is not supposed to. Showing it a red "no heartbeat"
  // pill for the 23 hours a day it is correctly not running would train the operator to ignore
  // the pill on the two daemons where it is the fault signal.
  const expectsBeat = job.heartbeat !== false;

  return (
    <div
      className={`rounded-sm border px-3 py-3 ${unheld ? 'border-bad/40 bg-bad-bg' : 'border-border'}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[15px] font-[560]">{ROLE_TITLE[job.role] ?? job.role}</div>
        <div className="flex gap-2">
          <Pill tone={held ? 'ok' : unheld ? 'bad' : 'warn'}>
            {held ? 'launchd holds it' : unheld ? 'NOT HELD' : 'launchd unknown'}
          </Pill>
          {expectsBeat ? (
            <Pill tone={beating ? 'ok' : beat?.present ? 'warn' : 'bad'}>
              {beating ? 'beating' : beat?.present ? 'silent' : 'no heartbeat'}
            </Pill>
          ) : (
            <Pill tone="ok">on a schedule</Pill>
          )}
        </div>
      </div>

      <div className="mt-1 text-[13px] text-muted">{job.what}</div>

      {unheld ? (
        <Problem>
          launchd is not holding this job, so nothing starts it.{' '}
          {job.plist_exists
            ? 'Start bootstraps it from its plist.'
            : job.installable
              ? 'It has never been installed. Start copies the tracked plist from deploy/ and bootstraps it.'
              : 'There is no plist here and none in deploy/, so Start has nothing to install.'}
        </Problem>
      ) : null}
      {job.error ? <Problem>{job.error}</Problem> : null}

      <div className="mt-2 text-[12px] text-subtle">
        <div>
          pid <span className="font-mono">{job.pid ?? beat?.pid ?? ABSENT}</span> · launchctl says{' '}
          <span className="font-mono">{job.reason}</span>
        </div>
        {expectsBeat ? (
          <div>
            last beat {beat?.ts ? ago(beat.ts) : ABSENT}
            {beat?.phase ? ` · ${beat.phase}` : ''}
            {beat?.code ? ` · code ${beat.code}` : ''}
          </div>
        ) : null}
        <div className="wrap-any font-mono">{job.label}</div>
      </div>

      <div className="mt-3">
        <Confirm
          action="daemon.restart"
          kind={held ? 'danger' : 'primary'}
          label={held ? 'Restart it' : 'Start it'}
          payload={() => ({ label: job.label, actor: 'ops-console', nonce: nonce() })}
          renderPreview={(p) => (
            <div className="flex flex-col gap-1">
              <div>{String(p.effect ?? '')}</div>
              <div className="text-[12px] text-muted">
                plist: <span className="font-mono">{String(p.plist ?? '')}</span>
              </div>
            </div>
          )}
          onApplied={onDone}
        />
      </div>
    </div>
  );
}

function PauseCard({ s, onDone }: { s: Scope; onDone: () => void }) {
  const [reason, setReason] = useState('');
  const armed = s.armed;
  return (
    <div className={`rounded-sm border px-3 py-3 ${armed ? 'border-warn bg-warn-bg' : 'border-border'}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[15px] font-[560]">{SCOPE_TITLE[s.scope] ?? s.scope}</div>
        <Pill tone={armed ? 'warn' : 'ok'}>{armed ? 'STOPPED' : 'running'}</Pill>
      </div>
      <div className="mt-1 text-[13px] text-muted">
        Stops: <span className="text-text">{s.stops}</span>
      </div>
      <div className="text-[13px] text-muted">
        Keeps running: <span className="text-text">{s.keeps_running}</span>
      </div>
      <div className="mt-1 text-[12px] text-subtle">{s.note}</div>
      {armed ? (
        <div className="mt-2 text-[12px] text-warn-strong">
          armed {ago(s.armed_at)} by <span className="font-mono">{s.actor || 'unknown'}</span>
          {s.reason ? ` — ${s.reason}` : ''}
        </div>
      ) : null}

      <div className="mt-3 flex flex-col gap-2">
        {!armed ? (
          <>
            <label className="text-[12px] text-muted" htmlFor={`why-${s.scope}`}>
              Why (required — an unexplained pause reads as a crash)
            </label>
            <input
              id={`why-${s.scope}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="tap rounded-sm border border-border-control bg-surface px-2 text-[16px]"
              placeholder="e.g. spend spike while I look at the ledger"
            />
            <Confirm
              action="pause.arm"
              kind="danger"
              label={`Stop: ${SCOPE_TITLE[s.scope] ?? s.scope}`}
              disabled={!reason.trim()}
              payload={() => ({ scope: s.scope, reason: reason.trim(), nonce: nonce() })}
              renderPreview={(p) => (
                <div className="flex flex-col gap-1">
                  <div>
                    This arms <span className="font-mono">{String(p.scope)}</span>.
                  </div>
                  <div>Stops: {String(p.stops)}</div>
                  <div>Keeps running: {String(p.keeps_running)}</div>
                  {p.already_armed ? <div>It is already armed; the first armer keeps the credit.</div> : null}
                </div>
              )}
              onApplied={onDone}
            />
          </>
        ) : (
          <Confirm
            action="pause.disarm"
            kind="primary"
            label="Start it again"
            payload={() => ({ scope: s.scope, nonce: nonce() })}
            renderPreview={(p) => (
              <div className="flex flex-col gap-1">
                <div>
                  This removes <span className="font-mono">{String(p.scope)}</span>.
                </div>
                <div>{String(p.effect ?? '')}</div>
              </div>
            )}
            onApplied={onDone}
          />
        )}
      </div>
    </div>
  );
}

/**
 * The roster editor.
 *
 * Deliberately not a dropdown you can brush past. This is the highest blast radius write in the
 * portal: it decides which brain may rule a verdict FINALLY, and therefore what can reach the
 * shelf. It needs a typed roster, a reason, the confirmation token, and a separate explicit
 * acknowledgement — the gateway refuses without the last one (`console_api.py:981`).
 */
function RosterEditor({ routing, onDone }: { routing: Routing; onDone: () => void }) {
  const [tiers, setTiers] = useState(routing.moat_primary_declared.join(', '));
  const [reason, setReason] = useState('');
  const [ack, setAck] = useState(false);

  return (
    <div className="rounded-sm border border-bad/40 bg-bad-bg px-3 py-3">
      <div className="text-[14px] font-[560] text-bad-strong">
        Change which brains may rule a verdict
      </div>
      <p className="mt-1 text-[13px] text-text">
        This is the publish gate. A tier outside this list still runs, but everything it rules is
        stamped provisional and never reaches the shelf on a pass. Changing it is not a
        preference; it is a claim that the new roster measured well on the golden set.
      </p>

      <label className="mt-3 block text-[12px] text-muted" htmlFor="roster">
        Trusted tiers, in order
      </label>
      <input
        id="roster"
        value={tiers}
        onChange={(e) => setTiers(e.target.value)}
        className="tap w-full rounded-sm border border-border-control bg-surface px-2 font-mono text-[16px]"
      />
      <div className="mt-1 text-[12px] text-subtle">
        Currently: <span className="font-mono">{routing.moat_primary_declared.join(', ')}</span> ·
        buildable: <span className="font-mono">{routing.buildable.join(', ')}</span>
      </div>

      <label className="mt-3 block text-[12px] text-muted" htmlFor="roster-why">
        Why (required)
      </label>
      <input
        id="roster-why"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        className="tap w-full rounded-sm border border-border-control bg-surface px-2 text-[16px]"
        placeholder="e.g. three golden runs at discrimination 1.00"
      />

      <label className="mt-3 flex items-start gap-2 text-[13px]">
        <input
          type="checkbox"
          checked={ack}
          onChange={(e) => setAck(e.target.checked)}
          className="mt-1 h-5 w-5"
        />
        <span>
          I understand this changes which verdicts may publish, and that it drops certification
          until the golden set is re-run.
        </span>
      </label>

      <div className="mt-3">
        <Confirm
          action="routing.set_moat_primary"
          kind="danger"
          label="Change the trusted roster"
          applyLabel="Yes — change who may rule"
          disabled={!tiers.trim() || !reason.trim() || !ack}
          payload={() => ({
            tiers: tiers.trim(),
            reason: reason.trim(),
            acknowledge_moat: true,
            nonce: nonce(),
          })}
          renderPreview={(p) => (
            <div className="flex flex-col gap-1">
              <div>
                Before: <span className="font-mono">{JSON.stringify(p.before)}</span>
              </div>
              <div>
                After: <span className="font-mono">{JSON.stringify(p.after)}</span>
              </div>
              <div>
                Becomes provisional:{' '}
                <span className="font-mono">
                  {JSON.stringify(p.becomes_provisional) || '[]'}
                </span>
              </div>
              {p.would_be_refused ? (
                <div className="text-bad-strong">
                  The engine would refuse this: {JSON.stringify(p.problems)}
                </div>
              ) : null}
              <div className="text-[12px] text-muted">Takes effect: {String(p.takes_effect)}</div>
            </div>
          )}
          onApplied={onDone}
        />
      </div>
    </div>
  );
}

/**
 * A nonce per attempt.
 *
 * The gateway dedupes on the STORED nonce in the intent log, not on a TTL cache, so a double-tap
 * on a phone — or a retry after a flaky tailnet hop — writes once and returns the first receipt.
 */
function nonce(): string {
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
