import React from 'react';
import Link from 'next/link';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import killTotals from '@/data/kill-log-totals.json';
import killNames from '@/data/kill-log-names.json';

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

/* Reads `kill-log-names.json`, NOT the full `kill-log.json`.
   This component renders three names and three gate labels. The full log is now ~507 KB (400
   entries with reasons and citations, for the `/kill-log` instrument), and a static JSON import
   is one value that cannot be tree-shaken -- importing it here would have shipped every reason
   and every citation in the HOME PAGE bundle to draw three lines of text. The names file carries
   `title` and `gate` for the newest 60 kills and nothing else. */
type KillEntry = {
  title: string;
  gate: string;
};

const ENTRIES: KillEntry[] = killNames as KillEntry[];

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
        // A light ledger, not a black terminal (brand v3, 2026-08-06). The slab version wore
        // `border-2 border-text bg-text` plus a 3px hard offset shadow -- a sticker sitting on
        // top of the page rather than a card in it -- and it forced every colour inside to be an
        // inverted `--on-band-*` token. Red and green are the only colour above the fold now,
        // and this is the one card where they carry meaning: killed vs survived.
        //
        // `text-left` is not decoration, it is insulation: text-align inherits, and this card is
        // dropped into hero wrappers that have carried `text-center` on mobile. A log that
        // ragged-centres its own entries reads as decoration, which is the opposite of its job.
        'overflow-hidden rounded-md border border-border bg-surface text-left',
        className,
      )}
    >
      {/* Header. Labelled as what it is, a snapshot of the audit trail, rather than "LIVE". */}
      <div className="flex h-11 items-center justify-between gap-3 border-b border-border px-5">
        <span className="text-meta font-semibold text-text">The filter log</span>
        <span className="truncate font-mono text-caption text-subtle">
          <span className="text-danger">{killed.toLocaleString('en-GB')} killed</span>
          {' · '}
          <span className="text-success">{passed.toLocaleString('en-GB')} survived</span>
        </span>
      </div>

      {/* The body: three real kills from the same JSON the /kill-log page renders. */}
      <div className="px-5">
        {KILL_LINES.map((k, i) => (
          /* `items-start`, not `items-baseline`, because the gate wraps under the name on a
             narrow card instead of being truncated. The old single-line `truncate` cut the text
             mid-word at 390px ("killed by value dura…"), which hid the gate, and the gate is
             the entire point of the row. */
          <div key={i} className="flex items-start gap-2 border-b border-border py-2.5 last:border-b-0">
            <span className="mt-0.5 shrink-0 text-caption text-danger" aria-hidden>✕</span>
            <span className="min-w-0">
              <span className="block break-words text-meta font-medium text-text">{k.name}</span>
              <span className="block font-mono text-caption text-subtle">killed by {k.gate}</span>
            </span>
          </div>
        ))}
      </div>

      <div className="border-t border-border px-5 py-3">
        <Link
          href="/kill-log"
          className="inline-flex items-center gap-1 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
        >
          Read the kill log
          <Icon name="arrowRight" size={14} />
        </Link>
      </div>
    </div>
  );
}
