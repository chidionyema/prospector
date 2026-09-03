import Link from 'next/link';

import { textLinkClass } from '@/components/ui';
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
 * THE CHART IS `.barline` NOW, NOT THE SPARKLINE (founder, 2026-08-30, pointing at this band:
 * "THE STYLONG HERE 24 ... IS SHIT", "IT LOOKS WEORD AND HAS DONE SINCE IT WAS INTROCDEC").
 *
 * It was six vertical cells in `.bars`. Measured on the production build at 1280 on 2026-08-30:
 * the box is 846.3x44px and the six cells render 44.0, 14.5, 13.6, 10.1, 5.7 and 3.5px tall, so
 * five of the six are under fifteen pixels and the whole chart occupies 171px of an 846px box.
 * It carried `aria-hidden`, so a screen reader was told the only ranked evidence on the band is
 * decoration, and one `.barkey` line named one bar for six bars, so five had no label at all.
 *
 * The comment that stood here said pairing each label with its own bar "needs a CSS rule that
 * `mumchimp.css` does not have". That was wrong, and it shipped on the strength of being written
 * down. `mumchimp.css:104-109` is `.barline`: a `1fr 48px` grid with a label, a 9px track and the
 * count in mono. The shipped stylesheet draws exactly this chart; nobody used it here.
 * `/kill-log` has rendered the same ranked chart from the same rule since 2026-08-18.
 *
 * Two utilities come with it, for the reason `killLogBars.test.ts` records: `.bars` is one class
 * name over two components, so the sparkline's `height:44px` (`mumchimp.css:103`) and its
 * `max-width:26px` cell cap (`mumchimp.css:356`) both land on this chart and have to be undone at
 * the call site. `mumchimp.css` is shipped verbatim and is not touched.
 */

const byGate = (killTotals as { byGate: Record<string, number> }).byGate;
const ranked = Object.entries(byGate).sort((a, b) => b[1] - a[1]);
const gates = ranked.slice(0, 6);
const top = gates[0];

export function KillGateBand() {
  const max = top[1];
  /* No `.wrap` here. This band sits inside the catalogue Section's 1080
     measure; a second wrap added 20px gutters on top of the section's, so
     the band read 40px narrower than the tiles above it and the filters
     below it. The band is the section's child and shares that edge. */
  return (
      <section className="band">
      <div className="band-in">
        <p className="fig num">{top[1].toLocaleString('en-GB')}</p>
        <div>
          {/* h3, because that is the only heading level the bundle draws inside a band
              (mumchimp.css:352, `.band h3`: 19px / 650 / -.018em). As an h4 it matched no rule
              and rendered at 16px / weight 400 on the built page, measured 2026-08-30. The
              outline is unaffected: the band sits under the h2 that heads its section. */}
          <h3>What 1,364 ideas didn&apos;t pass, and why</h3>
          <p>
            Of {RESEARCH_STATS.killed.toLocaleString('en-GB')} rejections, {top[1].toLocaleString('en-GB')}{' '}
            died on the same one: the idea cleared every hard gate and still did not score high
            enough to be worth your money. Not illegal, not already taken, not unfounded. Just not
            good enough to publish.
          </p>
          {/* Every bar is drawn against the LARGEST cause, not against the total. Against the
              total every bar but the first is a sliver and the picture says nothing; against the
              max, the comparison the reader came for is the one the chart makes. The floor of
              0.6% keeps a real cause visible rather than rendering it as an empty track. */}
          <ul className="bars h-auto items-stretch">
            {gates.map(([gate, n]) => (
              <li key={gate} className="barline">
                <span className="t max-sm:flex-col max-sm:items-start max-sm:gap-2">
                  {/* `.barline .lab` truncates at 52% with an ellipsis, which on a phone cuts the
                      cause of a rejection in half -- and the label IS the finding. Below `sm` it
                      takes the row and wraps, exactly as `/kill-log` does. */}
                  <span className="lab max-sm:max-w-none max-sm:whitespace-normal">
                    {GATE_LABELS[gate] ?? gate}
                  </span>
                  {/* `flex-none` BELOW `sm`, OR THE BAR HAS NO HEIGHT AT ALL. `.t` turns into a
                      column here, and in a column container the bar's height is its flex-basis,
                      not the `height:9px` on `.barline .bar`. Measured on the built page at 390
                      on 2026-08-31, on `/kill-log` which has shipped this markup since
                      2026-08-18: the bar computed `flex: 1 0 100%` and RENDERED 0px tall, so the
                      chart drew labels and counts with no bars under them. `flex-none` puts the
                      basis back to auto, which is what lets the 9px through. */}
                  <span className="bar max-sm:w-full max-sm:flex-none">
                    <i
                      className="max-w-none"
                      style={{ width: `${Math.max((n / max) * 100, 0.6)}%` }}
                    />
                  </span>
                </span>
                <span className="n num">{n.toLocaleString('en-GB')}</span>
              </li>
            ))}
          </ul>
          {/* The key says what is NOT on the chart. Six labelled rows need no legend, but a
              reader who counts them is owed the fact that more causes exist, and the count comes
              from the data rather than being typed. The kill log holds the rest. */}
          <p className="barkey">The six commonest of {ranked.length} recorded causes.</p>
          {/* `textLinkClass`, NOT a bare link inside `.src`. The bundle gives `.src a` a colour
              and nothing else (`mumchimp.css:.src a{color:var(--link)}`), and the paragraph around
              it is `--ink-3`. axe measured that pair at 2.31:1 on the live site on 2026-08-30
              (run 33339472255, `link-in-text-block`, serious, at both 390 and 1280): under the
              3:1 minimum, and with no underline there is no second cue, so the link is invisible
              to anyone who cannot separate those two greys. The helper is the one in-prose link
              treatment in this tree and carries a permanent underline for exactly this reason. */}
          <p className="src num">
            Every rejection published with its reason ·{' '}
            <Link href="/rejected" prefetch={false} className={textLinkClass()}>read the rejected ideas</Link>
          </p>
        </div>
      </div>
    </section>
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
          {/* The same defect as the band above, and axe reported it as the second node on the
              same rule. `textLinkClass` for the same reason. */}
          <p className="src num">
            Average {Math.round(sourcesTotal / packCount)} sources per pack ·{' '}
            <Link href="/how-it-works" className={textLinkClass()}>how the filter works</Link>
          </p>
        </div>
      </div>
    </section>
    </div>
  );
}
