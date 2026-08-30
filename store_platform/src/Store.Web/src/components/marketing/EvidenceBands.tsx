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

/*
 * THE CANONICAL NAMES, NOT THIS FILE'S OWN SHORTHAND (fix prompt D7, 2026-08-18).
 *
 * These read "Ungrounded", "Durability", "Affordability" -- one-word engine-adjacent labels
 * written here so six of them would fit on one `.barkey` line. The kill log names the same six
 * causes in full ("The defensibility claim was not evidence-backed"), so the two pages disagreed
 * about what killed an idea, on the band whose whole point is that the reason is published. The
 * shared map is `lib/gateLabels.ts`; this file no longer keeps a second copy to drift from.
 */
import { GATE_LABELS } from '@/lib/gateLabels';

/*
 * THE KEY NAMES ONE BAR, NOT SIX (2026-08-19).
 *
 * It printed all six canonical gate names joined by "·". Measured on the live page at 1280 with
 * Playwright: `.barkey` rendered 518x124px -- five wrapped lines of 11.5px mono under a 44px-tall
 * chart -- and at 390 it rendered 310x198px. It read as a paragraph, not a key, and no label sat
 * under the bar it named, so it told a reader nothing about which bar was which anyway.
 *
 * Short labels are not the way back. They were removed on 2026-08-18 because this file and the
 * kill log then named the same cause of death two different ways. The canonical names stay.
 *
 * So the key names the bar the copy is about and says what the rest are. Pairing each label with
 * its own bar needs a CSS rule that `mumchimp.css` does not have, and this build writes no CSS.
 */

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
          {/* h3, because that is the only heading level the bundle draws inside a band
              (mumchimp.css:352, `.band h3`: 19px / 650 / -.018em). As an h4 it matched no rule
              and rendered at 16px / weight 400 on the built page, measured 2026-08-30. The
              outline is unaffected: the band sits under the h2 that heads its section. */}
          <h3>The check that kills most ideas is not the one people expect</h3>
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
          <p className="barkey">
            Tallest bar: {GATE_LABELS[top[0]] ?? top[0]}. The five after it are the next commonest
            causes, in order.
          </p>
          <p className="src num">
            Every kill published with its reason · <Link href="/kill-log" prefetch={false}>read the kill log</Link>
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
          {/* h3, for the reason given on the band above: `.band h3` is the drawn style. */}
          <h3>Nothing here rests on a number we cannot show you</h3>
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
