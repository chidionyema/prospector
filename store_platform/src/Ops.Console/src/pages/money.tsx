/**
 * Money — can the shop take money right now, and would we know if it could not.
 *
 * The one number that matters is the rail's mode, and it has three failure shapes, not one:
 * `test` (a card is never charged), never-ran (nothing checked at all), and unreachable (the
 * measurement failed). They are rendered differently on purpose. A screen that paints a missing
 * answer the same colour as a healthy one is worse than no screen.
 *
 * The gaps are rendered as loudly as the facts. Today's revenue and the dispute list have no
 * route on the store API, so this page names the route that would close each gap instead of
 * showing an empty panel that reads as zero.
 */
import Link from 'next/link';
import Shell from '@/components/Shell';
import { AsOf, Card, Note, Pill, Problem, Row, Stat } from '@/components/ui';
import { ABSENT } from '@/lib/time';
import { useOps } from '@/lib/useOps';

type Rail = {
  state: 'live' | 'test' | 'never-ran' | 'unreachable';
  mode: string | null;
  provider: string | null;
  environment: string | null;
  decided_at: string | null;
  error: string | null;
  source?: string;
};
type ShelfMoney = {
  reachable: boolean;
  listed: number | null;
  registered: number | null;
  unsellable: number | null;
  error: string | null;
  source?: string;
};
type Gap = { id: string; what: string; needs: string; why: string };
type MoneyView = {
  rail: Rail;
  shelf: ShelfMoney;
  missing: Gap[];
  /** Writes the console cannot do. Optional so an older gateway payload still renders. */
  missing_actions?: Gap[];
  warnings: string[];
};

const RAIL_TONE: Record<Rail['state'], 'ok' | 'warn' | 'bad'> = {
  live: 'ok',
  test: 'bad',
  'never-ran': 'bad',
  unreachable: 'warn',
};

const RAIL_WORDS: Record<Rail['state'], string> = {
  live: 'Live keys. A checkout charges a real card.',
  test: 'Test keys. Every checkout completes and no card is charged.',
  'never-ran': 'The startup gate recorded no decision, so nothing checked the rail.',
  unreachable: 'The API did not answer. This is a failed measurement, not a healthy rail.',
};

export default function Money() {
  const { data, envelope, error } = useOps<MoneyView>('money');

  return (
    <Shell title="Money" intro="Whether the shop can take money, and what is not yet measured.">
      {error ? <Problem>{error}</Problem> : null}
      {(data?.warnings ?? []).map((w) => (
        <Problem key={w}>{w}</Problem>
      ))}

      {data ? (
        <>
          <Card
            title="The rail"
            tone={RAIL_TONE[data.rail.state]}
            right={<AsOf asOf={envelope?.as_of} tookMs={envelope?.took_ms} />}
          >
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat label="mode" value={data.rail.mode} tone={RAIL_TONE[data.rail.state] === 'ok' ? 'plain' : 'bad'} />
              <Stat label="provider" value={data.rail.provider} />
              <Stat label="environment" value={data.rail.environment} />
            </div>
            <p className="wrap-any mt-3 text-[13px] text-muted">{RAIL_WORDS[data.rail.state]}</p>
            <Row label="Decided at">{data.rail.decided_at ?? ABSENT}</Row>
            {data.rail.error ? <Note>{data.rail.error}</Note> : null}
            {data.rail.source ? <Note>{data.rail.source}</Note> : null}
          </Card>

          <Card title="What can be bought" tone={data.shelf.unsellable ? 'warn' : 'ok'}>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat label="listed" value={data.shelf.listed} />
              <Stat label="registered" value={data.shelf.registered} />
              <Stat
                label="not on offer"
                value={data.shelf.unsellable}
                tone={data.shelf.unsellable ? 'warn' : 'plain'}
              />
            </div>
            <p className="wrap-any mt-3 text-[13px] text-muted">
              The gap is work that passed every gate and cannot be sold. It is repaired on the{' '}
              <Link className="underline" href="/shelf">
                Stranded
              </Link>{' '}
              screen.
            </p>
            {data.shelf.error ? <Note>{data.shelf.error}</Note> : null}
          </Card>

          <Card title="Not measured yet" tone="warn">
            <p className="text-[13px] text-muted">
              These are gaps in the console, not readings of zero. Each names the route that
              closes it.
            </p>
            <div className="mt-2 flex flex-col gap-3">
              {data.missing.map((gap) => (
                <div key={gap.id} className="border-t border-border pt-2">
                  <div className="flex items-baseline gap-2">
                    <Pill tone="warn">{gap.id}</Pill>
                    <span className="text-[13px] font-[520]">{gap.what}</span>
                  </div>
                  <p className="wrap-any mt-1 font-mono text-[11px] text-subtle">{gap.needs}</p>
                  <p className="wrap-any mt-1 text-[12px] text-muted">{gap.why}</p>
                </div>
              ))}
            </div>
          </Card>

          {(data.missing_actions ?? []).length ? (
            <Card title="Cannot be done from here" tone="warn">
              <p className="text-[13px] text-muted">
                A money screen with no refund button reads as &ldquo;refunds happen
                elsewhere&rdquo;, and nobody can tell whether that is true. Named here, each is a
                gap with an owner.
              </p>
              <div className="mt-2 flex flex-col gap-3">
                {(data.missing_actions ?? []).map((gap) => (
                  <div key={gap.id} className="border-t border-border pt-2">
                    <div className="flex items-baseline gap-2">
                      <Pill tone="warn">{gap.id}</Pill>
                      <span className="text-[13px] font-[520]">{gap.what}</span>
                    </div>
                    <p className="wrap-any mt-1 font-mono text-[11px] text-subtle">{gap.needs}</p>
                    <p className="wrap-any mt-1 text-[12px] text-muted">{gap.why}</p>
                  </div>
                ))}
              </div>
            </Card>
          ) : null}
        </>
      ) : (
        <Card>asking the rail…</Card>
      )}
    </Shell>
  );
}
