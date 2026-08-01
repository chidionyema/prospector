import React from 'react';
import { Icon } from '@/components/ui';

/**
 * The single source of truth for "what is in the £49 download".
 *
 * Deliberately shared by the homepage and every pack page: when this claim lives in two places it
 * drifts, and a drifted claim on a paid product is a refund. It drifted anyway, this list said
 * FOUR documents while `prospector/bridge.py::BUNDLE_FILES` had grown to eight, so three real
 * deliverables (executive summary, first-week checklist, marketing assets) were shipped to buyers
 * without ever being advertised. A prose audit note dated to one afternoon could not catch that.
 *
 * So the note is replaced by a mechanism. `filename` on each entry below is the real zip entry,
 * and `__tests__/packContents.test.ts` reads `BUNDLE_FILES` out of the Python source and asserts
 * this list covers exactly those files, in that order. Adding a file to the bundle without
 * telling buyers about it now fails `npm test`.
 *
 * The other half of the guarantee is engine-side: `bridge.py` re-audits the written zip and ANDs
 * the result into `is_listed`, so a pack missing any of these files cannot be listed for sale.
 * Together they are what makes the eight-document claim true of every pack on the shelf rather
 * than true on average.
 *
 * Word and link floors are measured, not aspirational: across the bundles live on 2026-07-27 the
 * smallest was 5,069 words and the smallest link count 23 (median 7,523 / 119). The floor has to
 * be true of the weakest pack, not the best one.
 *
 * Format is Markdown in a zip, not PDF. Said plainly, and framed as the advantage it actually is.
 */
export const PACK_CONTENTS: {
  emoji: string;
  title: string;
  /** The real entry in the bundle zip. Pinned to BUNDLE_FILES by the drift test. */
  filename: string;
  desc: string;
  /** Appends the pack's real cited-source count. Only the QA report earns it. */
  showSourceCount?: boolean;
}[] = [
  {
    emoji: '🧭',
    title: 'Executive Summary',
    filename: '00_Executive_Summary.md',
    desc:
      'The opportunity in one page: what it is, the grounded signals that survived the checks, and an explicit list of what the pack does NOT claim. Read this first to decide if it is for you.',
  },
  {
    emoji: '📄',
    title: 'The Blueprint (Build Spec)',
    filename: '01_Blueprint_BuildSpec.md',
    desc:
      'What is actually being built, and in what order. Phased build plan, the recommended stack, the explicit non-goals for v1, and a straight section on what would kill this.',
  },
  {
    emoji: '🎯',
    title: 'The Go-To-Market Plan',
    filename: '02_Marketing_Plan_GTM.md',
    desc:
      'Where your first customers come from. The named channels and the communities behind them, the positioning you lead with, the beachhead to start in, and the kill criteria that tell you to stop.',
  },
  {
    emoji: '🛠️',
    title: 'The Operations Plan',
    filename: '03_Operations_Plan.md',
    desc:
      'How the thing actually runs once someone pays. Delivery workflow, capacity limits, the compliance gates you cannot skip, and where the manual work really sits.',
  },
  {
    emoji: '📊',
    title: 'The Financial Model',
    filename: '04_Financial_Model.md',
    desc:
      'Pricing mechanics and unit economics. Figures the engine could not ground are marked as absent rather than filled in, no invented revenue, cost or TAM.',
  },
  {
    emoji: '✅',
    title: 'First-Week Checklist',
    filename: '05_First_Week_Checklist.md',
    desc:
      'Six concrete steps for days one to seven: confirm the buyer, sketch the smallest paid offer, pick one channel and ignore the rest, and log what you could not verify.',
  },
  {
    emoji: '✍️',
    title: 'Marketing Assets',
    filename: 'Marketing_Assets.md',
    desc:
      'Launch copy you can send today, listing page, outreach and social drafts. Every asset passes the same claim-check as the research, so nothing here overstates the product.',
  },
  {
    emoji: '🔗',
    title: 'The QA Report, with the receipts',
    filename: 'QA_Report.md',
    showSourceCount: true,
    desc:
      'All six checks, each verdict, and a clickable source behind every claim. This is the file that proves the rest of the pack is not invented.',
  },
];

/**
 * "What's inside your download", the deliverable breakdown.
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
                {hasCount && item.showSourceCount && (
                  <span className="ml-1.5 font-normal text-muted">({sourceCount} sources)</span>
                )}
              </span>
              {/* The real zip entry. A buyer's fear at £49 is a thin Google Doc, and a filename
                  they can check against the download they receive is a falsifiable answer to it
                  in a way another adjective is not. */}
              <span className="mt-1 font-mono text-[11px] font-semibold text-muted">
                {item.filename}
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
