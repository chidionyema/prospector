import React from 'react';
import { Icon } from '@/components/ui';

/**
 * The single source of truth for "what is in the £49 download".
 *
 * Deliberately shared by the homepage and every pack page: when this claim lives in two places it
 * drifts, and a drifted claim on a paid product is a refund. Every line below is checked against
 * the real bundles in `publish/bundles/<id>/prospector_pack_<short>.zip` for all 15 live packs:
 *
 *   - 01_Blueprint_BuildSpec.md   present in 15/15
 *   - 02_Marketing_Plan_GTM.md    present in 15/15
 *   - operations + financials     present in 15/15, in one of two shapes: either
 *                                 03_Operations_Plan.md + 04_Financial_Model.md (10 packs), or
 *                                 03_Build_Launch_Kit.md, which carries an "Operational Plan"
 *                                 and a "Financial Model" section (5 packs)
 *   - QA_Report.md                present in 15/15
 *
 * Measured across those same 15 bundles: smallest is 5,069 words, median 7,523; smallest link
 * count is 23, median 119. Hence "5,000+ words" and a per-pack source count rather than a flat
 * "20+ pages" — the floor has to be true of the weakest pack, not the best one.
 *
 * Format is Markdown in a zip, not PDF. Said plainly, and framed as the advantage it actually is.
 */
export const PACK_CONTENTS: { emoji: string; title: string; desc: string }[] = [
  {
    emoji: '📄',
    title: 'The Blueprint (Build Spec)',
    desc:
      'What is actually being built, and in what order. Phased build plan, the recommended stack, the explicit non-goals for v1, and a straight section on what would kill this.',
  },
  {
    emoji: '🎯',
    title: 'The Go-To-Market Plan',
    desc:
      'Where your first customers come from. The named channels and the communities behind them, the positioning you lead with, the beachhead to start in, and the kill criteria that tell you to stop.',
  },
  {
    emoji: '🛠️',
    title: 'Operations and the Numbers',
    desc:
      'How it runs and what it earns. Delivery workflow, capacity, compliance gates, pricing mechanics and unit economics, with the figures the engine refuses to forecast marked as such.',
  },
  {
    emoji: '🔗',
    title: 'The QA Report, with the receipts',
    desc:
      'All six checks, each verdict, and a clickable source behind every claim. This is the file that proves the rest of the pack is not invented.',
  },
];

/**
 * "What's inside your download" — the deliverable breakdown.
 *
 * `sourceCount` is the pack's real cited-source count from the API; pass it on a pack page so the
 * receipts line is that pack's number, and omit it on the homepage where no single number is true.
 */
export function PackContentsSection({
  heading = 'What’s inside your download',
  lead,
  sourceCount,
  className,
}: {
  heading?: string;
  lead?: React.ReactNode;
  sourceCount?: number;
  className?: string;
}) {
  const hasCount = typeof sourceCount === 'number' && sourceCount > 0;
  return (
    <div className={className}>
      <h2 className="text-xl font-bold tracking-tight text-text md:text-2xl">{heading}</h2>
      {lead && <p className="mt-2 max-w-[64ch] text-sm leading-relaxed text-muted md:text-base">{lead}</p>}

      <ul className="mt-6 grid list-none grid-cols-1 gap-4 p-0 sm:grid-cols-2">
        {PACK_CONTENTS.map((item) => (
          <li
            key={item.title}
            className="flex gap-4 rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)]"
          >
            <span aria-hidden className="select-none text-2xl leading-none">
              {item.emoji}
            </span>
            <span className="flex flex-col">
              <span className="text-base font-bold leading-snug text-text">
                {item.title}
                {hasCount && item.emoji === '🔗' && (
                  <span className="ml-1.5 font-normal text-muted">({sourceCount} sources)</span>
                )}
              </span>
              <span className="mt-1.5 text-sm leading-relaxed text-text/70">{item.desc}</span>
            </span>
          </li>
        ))}
      </ul>

      {/* Format ambiguity kills digital conversions. State the file format outright. */}
      <div className="mt-5 flex flex-col gap-2 rounded-xl border border-border bg-bg/50 p-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm leading-relaxed text-text/75">
          <span className="font-bold text-text">Format:</span> one zip of plain Markdown files, 5,000+ words
          per pack. Open it anywhere, edit it, or paste it straight into Notion, Obsidian or your AI tool of
          choice. No PDF viewer, no login, no subscription.
        </p>
        <span className="inline-flex flex-none items-center gap-2 rounded-lg bg-success/10 px-3 py-2 text-xs font-bold text-success">
          <Icon name="download" size={14} />
          Instant download
        </span>
      </div>
    </div>
  );
}
