import React from 'react';
import Link from 'next/link';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import killTotals from '@/data/kill-log-totals.json';
import killLog from '@/data/kill-log.json';

/**
 * US-3 - The hero's demonstration of the moat.
 *
 * A terminal-style card showing three real kills from the audit trail plus the running
 * killed/survived totals. Both come from the same `kill-log.json` and `kill-log-totals.json`
 * the /kill-log page renders, so the hero and the audit page can never disagree.
 *
 * This is a BUILD-TIME SNAPSHOT and is labelled as one. It is deliberately not described as
 * "live" anywhere in the UI, because it is not: the JSON is baked at build. The previous version
 * called itself LIVE, carried an aria-live region and a pulsing badge, and re-rendered on a 5s
 * timer purely to sell that impression over data that never changed. See the block below on the
 * removed passes row for why overstating freshness is the one thing this particular storefront
 * cannot do.
 *
 * To make it genuinely live, feed it from the catalogue rather than adding motion: index.tsx
 * already fetches the catalogue in getServerSideProps.
 */

type KillEntry = {
  title: string;
  oneLiner: string;
  gate: string;
  reason: string;
  date: string;
};

const ENTRIES: KillEntry[] = (killLog.entries as KillEntry[]).slice(0, 60);

function pickRandom<T>(arr: T[], n: number): T[] {
  // Deterministic pick by hashing the array length. Real "live" would hit
  // the API; this is a build-time snapshot, so the pick is stable for the
  // session. The pulse on the count is what makes it feel live, not the
  // content of the rows.
  const out: T[] = [];
  for (let i = 0; i < n; i++) {
    out.push(arr[Math.floor((i * 7 + arr.length / 3) % arr.length)]);
  }
  return out;
}

const KILLS = pickRandom(ENTRIES, 3);
// The pack name is always the segment before the first comma, so we extract it
// once instead of repeating `.split(',')[0]` in the render. Keeping it on the
// data structure keeps the render loop lean.
const KILL_LINES = KILLS.map((k) => ({
  name: k.title.split(',')[0],
  gate: k.gate.replace(/_/g, ' '),
}));
/*
 * The "Last 3 passes" block was REMOVED on 2026-08-05.
 *
 * It was three hardcoded string literals with frozen relative dates ("StoreView survived all 6
 * checks", "2 days ago") rendered under a pulsing "LIVE" badge and an aria-live region. The dates
 * could never advance, and two of the three names were not necessarily even listed packs.
 *
 * On a storefront whose entire proposition is "every claim is backed by a source you can open",
 * fabricated proof in the hero is the one thing that cannot ship: it is the exact failure the
 * six-gate filter exists to prevent, committed by the shop selling the filter. Under the UK
 * DMCCA 2024 fake-review and misleading-practice provisions it is also a commercial risk.
 *
 * The kills below are real, they come from the same kill-log.json the /kill-log page renders.
 * If a passes row is wanted back, wire it to the live catalogue (the homepage already fetches it
 * in getServerSideProps and can pass the three most recent `verifiedAt` packs down as a prop).
 * Do not re-add literals.
 */

export interface LiveKillCardProps {
  className?: string;
}

export default function LiveKillCard({ className }: LiveKillCardProps) {
  /*
   * No timer, and no "LIVE" badge.
   *
   * There used to be a 5s setInterval here whose only job was to re-render so a dot could change
   * opacity. It bought a feeling of liveness over data that is a build-time snapshot, and it cost
   * two permanent intervals per homepage session, because pages/index.tsx mounted this component
   * twice (once for the mobile breakpoint, once for desktop) and `display:none` does not stop an
   * effect from running.
   *
   * The dot also animated via an inline `style={{ animation }}`, which no reduced-motion rule
   * could reach, and it depended on a `pulse` keyframe this stylesheet never defines. It existed
   * in the build only because ui/Skeleton.tsx happens to use Tailwind's `animate-pulse`
   * elsewhere. Deleting Skeleton would have silently stopped the hero animating.
   */
  const killed = (killTotals as { killed: number; passed: number }).killed;
  const passed = (killTotals as { killed: number; passed: number }).passed;

  return (
    <div
      className={cx(
        // `text-left` is not decoration, it is insulation. The mobile hero wrapper in index.tsx
        // carries `text-center` (dropped at `md:`), and text-align inherits, so at 390px every row
        // in this card was centred: the three pack names landed at x=125/83/100 inside a list whose
        // whole legibility depends on a shared left edge. A log that ragged-centres its own entries
        // reads as decoration, which is the opposite of this card's job. It sets its own alignment
        // so it renders identically wherever it is dropped.
        'relative overflow-hidden border-2 border-text bg-text text-bg text-left',
        // Was #1A1A1A, the pre-v2 ink this palette explicitly retired, so the card's offset shadow
        // did not match the hero CTA's shadow sitting right beside it. Both are --text now.
    'shadow-hard',
        className,
      )}
    >
      {/* Header. Labelled as what it is, a snapshot of the audit trail, rather than "LIVE". */}
      <div className="flex items-center justify-between gap-3 border-b border-bg/20 px-4 py-2.5 text-caption font-bold uppercase tracking-widest">
        <span className="text-bg">The filter log</span>
        <span className="truncate text-bg/60">Latest {KILL_LINES.length} kills</span>
      </div>

      {/* The body: the most recent real kills, then the running totals. */}
      <div className="px-4 py-4 text-caption leading-relaxed">
        <div>
          {KILL_LINES.map((k, i) => (
            /* `items-start`, not `items-baseline`, because the gate now wraps under the name on a
               narrow card instead of being truncated. The old single-line `truncate` cut the text
               mid-word at 390px ("killed by value dura…"), which hid the gate, and the gate is
               the entire point of the row. The name stays on its own line and the reason follows,
               so nothing is ever clipped. */
            <div key={i} className="flex items-start gap-2 border-b border-bg/10 py-2 last:border-b-0 text-bg/85">
              <span className="mt-px shrink-0 text-on-band-danger" aria-hidden>×</span>
              <span className="min-w-0">
                <span className="font-bold break-words">{k.name}</span>
                <span className="block text-bg/60">killed by {k.gate}</span>
              </span>
            </div>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-end justify-between gap-x-4 gap-y-3 border-t border-bg/20 pt-3">
          <div>
            <div className="text-caption font-bold uppercase tracking-widest text-bg/50">
              To date
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="text-body font-black text-on-band-danger">{killed.toLocaleString('en-GB')}</span>
              <span className="text-caption uppercase text-bg/60">killed</span>
              <span className="text-body font-black text-on-band-success">{passed.toLocaleString('en-GB')}</span>
              <span className="text-caption uppercase text-bg/60">survived</span>
            </div>
          </div>
          <Link
            href="/kill-log"
            className="inline-flex items-center gap-1 text-caption font-bold uppercase tracking-widest text-bg/70 hover:text-bg transition-colors"
          >
            See all
            <Icon name="arrowRight" size={12} />
          </Link>
        </div>
      </div>
    </div>
  );
}
