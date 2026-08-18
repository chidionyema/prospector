import Link from 'next/link';

import killTotals from '@/data/kill-log-totals.json';
import { RESEARCH_STATS } from '@/lib/stats';

/*
 * THE TWO ENGAGEMENT BANDS, from `mockups/index.html` sections 9 and 12.
 *
 * The drawing writes band one as "411 died on a single question: can the payer actually pay?".
 * That number is not ours. `src/data/kill-log-totals.json` says payer_solvency killed 48 and
 * min_composite killed 624, so the drawn copy would have printed a figure the data does not
 * support, which the source-or-die rule forbids. The band keeps the drawing's shape, its class
 * names and its point, and states the gate that actually kills most ideas here.
 */

const GATE_LABELS: Record<string, string> = {
  min_composite: 'Scored too low',
  incumbency: 'Already owned',
  moat_ungrounded: 'Ungrounded',
  adversarial_decisive: 'Adversarial',
  value_durability: 'Durability',
  payer_solvency: 'Affordability',
  source_or_die: 'No sources',
  legality: 'Legality',
  route_to_market: 'Route to market',
  pain_reality: 'Pain reality',
  currency: 'Out of date',
  distribution: 'Distribution',
  buyer_intent: 'Buyer intent',
};

const byGate = (killTotals as { byGate: Record<string, number> }).byGate;
const gates = Object.entries(byGate)
  .sort((a, b) => b[1] - a[1])
  .slice(0, 6);
const top = gates[0];

export function KillGateBand() {
  const max = top[1];
  return (
    <div className="wrap">
      <section className="band">
      <div className="band-in">
        <p className="fig dead num">{top[1].toLocaleString('en-GB')}</p>
        <div>
          <h4>The check that kills most ideas is not the one people expect</h4>
          <p>
            Of {RESEARCH_STATS.killed.toLocaleString('en-GB')} kills, {top[1].toLocaleString('en-GB')}{' '}
            died on the same one: the idea cleared every hard gate and still did not score high
            enough to be worth your money. Not illegal, not already taken, not unfounded. Just not
            good enough to publish.
          </p>
          <div className="bars" aria-hidden="true">
            {gates.map(([gate, n], i) => (
              <i
                key={gate}
                className={i === 0 ? 'hot' : undefined}
                style={{ height: `${Math.round((n / max) * 100)}%` }}
              />
            ))}
          </div>
          <p className="barkey">{gates.map(([g]) => GATE_LABELS[g] ?? g).join(' · ')}</p>
          <p className="src num">
            Every kill published with its reason · <Link href="/kill-log">read the kill log</Link>
          </p>
        </div>
      </div>
    </section>
    </div>
  );
}

export function SourcesBand({ sourcesTotal, packCount }: { sourcesTotal: number; packCount: number }) {
  if (!sourcesTotal || !packCount) return null;
  return (
    <div className="wrap">
      <section className="band">
      <div className="band-in">
        <p className="fig num">{sourcesTotal.toLocaleString('en-GB')}</p>
        <div>
          <h4>Nothing here rests on a number we cannot show you</h4>
          <p>
            Every figure in every pack links back to the page it came from: tribunal decisions, ONS
            tables, Companies House filings, council policy documents. Where a claim could not be
            verified, the pack says so and marks it, rather than filling the gap.
          </p>
          <p className="src num">
            Average {Math.round(sourcesTotal / packCount)} sources per pack ·{' '}
            <Link href="/how-it-works">how the filter works</Link>
          </p>
        </div>
      </div>
    </section>
    </div>
  );
}
