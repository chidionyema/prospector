/**
 * Spend — what was billed today, and how close the cap is.
 *
 * Two legs, kept apart, because merging them is how a dashboard reports a subscription's free
 * calls as money owed. `metered` is billed money and is the liability rail. `subscription` is
 * Claude Code CLI burn, which costs allowance rather than dollars.
 *
 * A `$0.00` with an unreadable ledger is NOT zero spend, and the engine says so in `warnings`.
 * Those warnings are rendered at full size, not as a footnote — the whole failure mode is a
 * confident zero.
 */
import Shell from '@/components/Shell';
import { AsOf, Card, Note, Pill, Problem, Row, Scroll, Stat } from '@/components/ui';
import { ABSENT, duration } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Leg = {
  usd: number | null;
  cap_usd: number | null;
  cap_key: string;
  warn_at_usd: number | null;
  enforced: boolean;
  pct_of_cap: number | null;
  fraction_of_cap: number | null;
  remaining_usd: number | null;
  state: string;
  what: string;
  projection: {
    rate_per_h: number | null;
    hit_in_h: number | null;
    hit_at: string | null;
    reason: string;
    caveat: string;
  };
};
type Attribution = {
  role?: string;
  name?: string;
  usd: number | null;
  attributable: boolean;
  reason: string;
  leg?: string;
};
type SpendView = {
  day: string;
  day_note: string;
  elapsed_h: number;
  hours_left_today: number;
  source: string;
  ledger: { path: string; present: boolean; size_bytes: number | null };
  cache: { path: string; present: boolean; lag_bytes: number | null; newest_day: string | null };
  legs: { metered: Leg; subscription: Leg };
  roles: Attribution[];
  tiers: Attribution[];
  warnings: string[];
};

export default function Spend() {
  const { data, envelope, error } = useOps<SpendView>('spend');

  return (
    <Shell title="Spend" intro="Billed money today, against the cap that stops the engine.">
      {error ? <Problem>{error}</Problem> : null}

      {(data?.warnings ?? []).map((w) => (
        <Problem key={w}>{w}</Problem>
      ))}

      {data ? (
        <>
          <LegCard
            title="Billed money"
            leg={data.legs.metered}
            envelope={{ as_of: envelope?.as_of, took_ms: envelope?.took_ms }}
            hoursLeft={data.hours_left_today}
          />
          <LegCard
            title="Subscription burn"
            leg={data.legs.subscription}
            hoursLeft={data.hours_left_today}
          />

          <Card title="Where it went">
            <p className="text-[13px] text-muted">
              A figure appears only where it can be attributed. Where a leg is shared between
              roles the engine says so instead of splitting it by guesswork.
            </p>
            <Scroll>
              <table className="mt-2 w-full min-w-[480px] border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-border text-left text-[12px] uppercase tracking-[0.06em] text-subtle">
                    <th className="py-2 pr-3 font-[520]">role</th>
                    <th className="py-2 pr-3 font-[520]">usd</th>
                    <th className="py-2 font-[520]">why</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {data.roles.map((r) => (
                    <tr key={r.role} className="border-b border-border align-top">
                      <td className="py-2 pr-3">{r.role}</td>
                      <td className="py-2 pr-3">
                        {r.usd === null ? <span className="text-faint">{ABSENT}</span> : `$${r.usd.toFixed(2)}`}
                      </td>
                      <td className="wrap-any py-2 text-[11px] text-muted">{r.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>

            <Scroll>
              <table className="mt-4 w-full min-w-[480px] border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-border text-left text-[12px] uppercase tracking-[0.06em] text-subtle">
                    <th className="py-2 pr-3 font-[520]">tier</th>
                    <th className="py-2 pr-3 font-[520]">leg</th>
                    <th className="py-2 pr-3 font-[520]">usd</th>
                    <th className="py-2 font-[520]">why</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {data.tiers.map((t) => (
                    <tr key={t.name} className="border-b border-border align-top">
                      <td className="py-2 pr-3">{t.name}</td>
                      <td className="py-2 pr-3 text-[11px]">{t.leg}</td>
                      <td className="py-2 pr-3">
                        {t.usd === null ? <span className="text-faint">{ABSENT}</span> : `$${t.usd.toFixed(2)}`}
                      </td>
                      <td className="wrap-any py-2 text-[11px] text-muted">{t.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
          </Card>

          <Card title="Where the numbers come from">
            <Row label="Day">
              {data.day} — {data.day_note}
            </Row>
            <Row label="Elapsed today">{duration(data.elapsed_h * 3600)}</Row>
            <Row label="Left today">{duration(data.hours_left_today * 3600)}</Row>
            <Row label="Read by">{data.source}</Row>
            <Row label="Ledger">
              {data.ledger.present ? data.ledger.path : `MISSING — ${data.ledger.path}`}
            </Row>
            <Row label="Scan cache">
              {data.cache.present
                ? `${data.cache.newest_day ?? ABSENT}${data.cache.lag_bytes ? ` · ${data.cache.lag_bytes}B behind` : ''}`
                : 'not present'}
            </Row>
          </Card>

          <Note>
            The cap is edited under{' '}
            <a className="underline" href="/config">
              Settings
            </a>{' '}
            — it is <span className="font-mono">spend.daily_cap_usd</span> in config.yaml, so a
            change takes effect on the next tick.
          </Note>
        </>
      ) : (
        <Card>reading the ledger…</Card>
      )}
    </Shell>
  );
}

function LegCard({
  title,
  leg,
  envelope,
  hoursLeft,
}: {
  title: string;
  leg: Leg;
  envelope?: { as_of?: number; took_ms?: number };
  hoursLeft: number;
}) {
  const tone =
    leg.state === 'over' || leg.state === 'blocked'
      ? 'bad'
      : leg.state === 'warn'
        ? 'warn'
        : leg.state === 'uncapped'
          ? 'warn'
          : 'ok';
  const pct = leg.fraction_of_cap === null ? null : Math.min(1, Math.max(0, leg.fraction_of_cap));

  return (
    <Card
      title={title}
      tone={tone}
      right={envelope ? <AsOf asOf={envelope.as_of} tookMs={envelope.took_ms} /> : <Pill tone={tone}>{leg.state}</Pill>}
    >
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Stat
          label="spent today"
          value={leg.usd === null ? null : `$${leg.usd.toFixed(2)}`}
          tone={tone === 'bad' ? 'bad' : 'plain'}
        />
        <Stat
          label="cap"
          value={leg.enforced && leg.cap_usd ? `$${leg.cap_usd.toFixed(2)}` : null}
          note={leg.enforced ? leg.cap_key : 'not enforced'}
          tone={leg.enforced ? 'plain' : 'warn'}
        />
        <Stat
          label="left"
          value={leg.remaining_usd === null ? null : `$${leg.remaining_usd.toFixed(2)}`}
        />
      </div>

      {pct !== null ? (
        <div className="mt-3 h-2 w-full rounded-sm bg-surface3" role="img" aria-label={`${Math.round(pct * 100)}% of cap`}>
          <div
            className={`h-2 rounded-sm ${tone === 'bad' ? 'bg-bad' : tone === 'warn' ? 'bg-warn' : 'bg-ok'}`}
            style={{ width: `${Math.round(pct * 100)}%` }}
          />
        </div>
      ) : null}

      {/* wrap-any, because these strings are engine prose that carries file paths and config keys.
          Measured 2026-08-16: the "No burn rate" reason ran 446px wide in a 342px card and pushed
          the whole page sideways by 90px at 390. A long unbroken token has no space to break at. */}
      <p className="wrap-any mt-3 text-[13px] text-muted">{leg.what}</p>

      <div className="wrap-any mt-2 text-[13px]">
        {leg.projection.rate_per_h === null ? (
          <span className="text-subtle">No burn rate: {leg.projection.reason}</span>
        ) : (
          <>
            Burning ${leg.projection.rate_per_h.toFixed(2)}/h.{' '}
            {leg.projection.hit_in_h === null
              ? 'It will not reach the cap today.'
              : `Reaches the cap in ${duration(leg.projection.hit_in_h * 3600)}${
                  leg.projection.hit_in_h > hoursLeft ? ' — after midnight, so not today.' : '.'
                }`}
          </>
        )}
      </div>
      {leg.projection.caveat ? <Note>{leg.projection.caveat}</Note> : null}
    </Card>
  );
}
