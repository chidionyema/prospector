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
 *
 * The `emoji` field is deleted (brand v3, 2026-08-06). Eight emoji stacked down a list render as
 * eight different pieces of third-party artwork -- a different set on macOS, Windows and Android --
 * on the one screen whose job is to look like a document worth £49. The file icon is now a single
 * consistent glyph from our own set, and the deliverable is identified by its real filename.
 */
export const PACK_CONTENTS: {
  title: string;
  /** The real entry in the bundle zip. Pinned to BUNDLE_FILES by the drift test. */
  filename: string;
  desc: string;
  /** Appends the pack's real cited-source count. Only the QA report earns it. */
  showSourceCount?: boolean;
}[] = [
  {
    title: 'Executive Summary',
    filename: '00_Executive_Summary.md',
    desc:
      'The opportunity on one page: what it is, what checked out, and what we do not claim.',
  },
  {
    title: 'The Blueprint (Build Spec)',
    filename: '01_Blueprint_BuildSpec.md',
    desc:
      'What to build, in what order, on what stack. Includes the non-goals for v1 and what would kill this.',
  },
  {
    title: 'The Go-To-Market Plan',
    filename: '02_Marketing_Plan_GTM.md',
    desc:
      'Where your first customers come from. Named channels, the beachhead to start in, and the signals that say stop.',
  },
  {
    title: 'The Operations Plan',
    filename: '03_Operations_Plan.md',
    desc:
      'How it runs once someone pays. Delivery, capacity limits, the compliance you cannot skip, and where the manual work sits.',
  },
  {
    title: 'The Financial Model',
    filename: '04_Financial_Model.md',
    desc:
      'Pricing and the numbers behind it. Anything we could not verify is marked missing, never made up.',
  },
  {
    title: 'First-Week Checklist',
    filename: '05_First_Week_Checklist.md',
    desc:
      'Six steps for days one to seven: confirm the buyer, size the smallest paid offer, pick one channel.',
  },
  {
    title: 'Marketing Assets',
    filename: 'Marketing_Assets.md',
    desc:
      'Launch copy you can send today: listing page, outreach, social. Claim-checked like the research.',
  },
  {
    title: 'The QA Report, with the receipts',
    filename: 'QA_Report.md',
    showSourceCount: true,
    desc:
      // Not "all six checks": the check set is lane-dependent, so this file carries eight or
      // nine verdicts on the packs vetted by the side-hustle lanes. The claim that is true of
      // every pack is "every check that was run, with its verdict and its source".
      'Every check this pack faced, each verdict, and a clickable source behind every claim.',
  },
];

/**
 * "What's inside your download", the deliverable breakdown.
 *
 * `sourceCount` is the pack's real cited-source count from the API; pass it on a pack page so the
 * receipts line is that pack's number, and omit it on the homepage where no single number is true.
 */
export function PackContentsSection({
  heading = 'What’s inside your pack',
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
      <h2 className="text-h2 font-semibold text-text">{heading}</h2>
      {lead && <p className="mt-2 max-w-[60ch] text-body text-muted">{lead}</p>}

      {/*
       * THE MANIFEST AS A FILE TREE, not eight bordered cards.
       *
       * The previous shape was a two-column grid of `rounded-md border border-border` cards, which
       * is the same object the shelf uses for products: eight cards saying "here are eight things"
       * read as eight things to choose between rather than as one archive with eight entries in
       * it. The tree says the true thing structurally -- these arrive together, in this order, in
       * one file -- and it says it before a word is read.
       *
       * The filenames were already here and are already pinned to `bridge.py::BUNDLE_FILES` by
       * `__tests__/packContents.test.ts`. What changes is that they stop being a caption under a
       * marketing title and become the primary column, which is the point: a buyer's fear at £49
       * is a thin Google Doc, and a listing of real entries they can check against the download is
       * a falsifiable answer to that in a way another adjective is not.
       *
       * The glyphs are literal box-drawing characters rather than borders or an SVG, because at
       * `text-caption` in the mono face they align on the same grid the filenames do. They are
       * inside an `aria-hidden` span: a screen reader announcing "box drawings light up and right"
       * before every filename is noise, and the `<ul>`/`<li>` structure already carries "this is a
       * list of eight items" losslessly.
       *
       * The root is NOT a zip filename. `bridge.py:813` writes `prospector_pack_<id8>.zip` locally
       * while the delivery key at `:632` is `packs/<id>/<content_hash>.zip`, so which of those a
       * buyer's browser saves is not a fact this component can state. It states the fact it has.
       */}
      <div className="mt-6 overflow-hidden rounded-md bg-surface">
        <div className="flex items-center gap-2 border-b border-border bg-surface2 px-5 py-3">
          <Icon name="download" size={14} className="flex-none text-subtle" />
          <span className="font-mono text-caption text-text">your pack/</span>
          <span className="ml-auto font-mono text-caption text-subtle">
            {PACK_CONTENTS.length} files
          </span>
        </div>
        <ul className="list-none p-0">
          {PACK_CONTENTS.map((item, i) => {
            const last = i === PACK_CONTENTS.length - 1;
            return (
              <li
                key={item.title}
                className="border-b border-border/60 px-5 py-4 last:border-b-0"
              >
                <div className="flex min-w-0 items-baseline gap-2">
                  <span aria-hidden className="flex-none font-mono text-caption text-faint">
                    {last ? '└──' : '├──'}
                  </span>
                  <span className="min-w-0 break-all font-mono text-caption text-text">
                    {item.filename}
                  </span>
                  {hasCount && item.showSourceCount && (
                    <span className="flex-none font-mono text-caption text-success">
                      {sourceCount} sources
                    </span>
                  )}
                </div>
                {/* Indented to the width of the glyph plus its gap, so the prose hangs off the
                    branch rather than restarting the line. `pl-[3.25rem]` is that measurement at
                    the caption size, not a round number chosen by eye. */}
                <div className="pl-[3.25rem]">
                  <span className="block text-meta font-semibold leading-snug text-text">
                    {item.title}
                  </span>
                  <span className="mt-1 block max-w-[70ch] text-meta leading-relaxed text-muted">
                    {item.desc}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {/* Format ambiguity kills digital conversions, so the format still gets stated outright --
          but it no longer LEADS. This box opened "Format: one zip of plain Markdown files", which
          answers "what is the container?" before the reader has been told what is in it. Markdown
          and zip are engineer words for a shopper, and putting them in the first three words made
          the £49 purchase sound like a developer artefact rather than eight finished documents.

          The Notion and Obsidian name-drops are GONE. They were two brands most readers do not
          use, spent to make one point ("it opens anywhere") that "paste anywhere" makes without
          asking anyone to recognise a product. Every fact in the old sentence survives; the zip is
          at the end, where it reads as "and it opens anywhere" rather than as the description of
          what you are buying. */}
      <div className="mt-4 flex flex-col gap-3 rounded-md border border-border bg-surface2 p-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-[62ch] text-meta text-muted">
          <span className="font-medium text-text">{PACK_CONTENTS.length} plain-text files in a zip,
          5,000+ words.</span>{' '}
          Yours to keep, edit, or paste anywhere. No login, no subscription.
        </p>
        <span className="inline-flex flex-none items-center gap-2 text-meta font-medium text-text">
          <Icon name="download" size={16} className="text-success" />
          Instant download
        </span>
      </div>
    </div>
  );
}
