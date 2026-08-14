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
 * The rest of the archive: real entries, deliberately NOT promises.
 *
 * These are `bridge.py::BUNDLE_BONUS_FILES`. The distinction is load-bearing and it is the reason
 * they get their own constant instead of being appended to the list above: `audit_bundle` iterates
 * BUNDLE_FILES only, and `is_listed` is ANDed with its result, so anything in PACK_CONTENTS is a
 * sellability CONTRACT -- a pack missing one cannot go on the shelf. A bonus file missing must
 * never delist a pack, so it must never enter that tuple.
 *
 * They were invisible here until 2026-08-14, and that was the actual complaint. The bundle grew a
 * typeset PDF, a printable first-fortnight sheet, a machine-readable assumptions table, the
 * evidence stated once, and a rendered reader (commit 40212a3); the shelf went on describing eight
 * Markdown files, so the one answer to "markdown files is not the one" was shipped to buyers and
 * advertised to nobody. A feature the shelf does not mention is a feature nobody buys.
 *
 * `__tests__/packContents.test.ts` pins this list to BUNDLE_BONUS_FILES the same way it pins the
 * one above to BUNDLE_FILES, so the next file added to the zip cannot go unmentioned either.
 */
export const PACK_EXTRAS: { title: string; filename: string; desc: string }[] = [
  {
    title: 'The whole pack, typeset',
    filename: 'Complete_Pack.pdf',
    desc: 'Every document above in one printable PDF. Open it on a phone, or put it in front of someone.',
  },
  {
    title: 'The evidence, in one place',
    filename: 'Evidence_and_Constraints.md',
    desc: 'Each check, what it found, and the source behind it, without hunting through the plans.',
  },
  {
    title: 'The first fortnight, on one page',
    filename: 'First_Fortnight.html',
    desc: 'A single sheet to print and work from. Days one to fourteen, nothing else on it.',
  },
  {
    title: 'The assumptions, as a table',
    filename: 'Assumptions.csv',
    desc: 'Every number the financial model rests on, in a file your spreadsheet opens directly.',
  },
  {
    title: 'A reader for the whole pack',
    filename: 'index.html',
    desc: 'Open this first and read the pack in order in your browser. No install, no account.',
  },
  {
    title: 'The machine-readable record',
    filename: 'manifest.jsonld',
    desc: 'What this pack is, in structured data, so a tool can read it as easily as you can.',
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
          {/* "documents", not "files". `PACK_CONTENTS` is the eight advertised DELIVERABLES, and
              the drift test pins it to `BUNDLE_FILES`. But the zip is not eight entries: bridge.py
              also writes everything in `PACK_EXTRAS` -- deliberately outside BUNDLE_FILES so a
              missing one cannot delist a pack, and so they do not trip that test. Measured
              2026-08-08 across the 45 packs then live, entry counts ran 8 (12 packs), 9 (14), 10
              (19), so most buyers counted nine or ten entries after being told eight. "Files" is a
              claim about the archive and it was false; "documents" is a claim about the
              deliverables and it is exactly what the first list is. The extras are now shown in
              their own group below rather than left as a surprise in the download. */}
          <span className="ml-auto font-mono text-caption text-subtle">
            {PACK_CONTENTS.length} documents
          </span>
        </div>
        <ul className="list-none p-0">
          {PACK_CONTENTS.map((item) => (
            <li key={item.title} className="border-b border-border/60 px-5 py-4">
              {/* THE DOCUMENT NAME LEADS, the filename trails it in faint mono.
                  Until 2026-08-14 this was the other way round: `00_Executive_Summary.md` was the
                  primary column at full text colour and "Executive Summary" was a caption under
                  it. The argument for that is written above and it was not a bad one -- a real
                  entry a buyer can check against their download is falsifiable in a way another
                  adjective is not. But the founder read the rendered page and the verdict was that
                  the shelf still reads as a directory listing of Markdown, which is the exact
                  impression "markdown files is not the one" was about. Eight snake_case filenames
                  stacked down the primary column say "you are buying some text files" before a
                  single title is read.
                  The filename is KEPT, not removed: deleting it would trade a real objection for a
                  vaguer product. Demoted to `text-faint` at the end of the line, it still answers
                  "what will I actually find in the zip?" without being the headline. */}
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                <span aria-hidden className="flex-none font-mono text-caption text-faint">
                  ├──
                </span>
                <span className="min-w-0 text-meta font-semibold leading-snug text-text">
                  {item.title}
                </span>
                <span className="min-w-0 break-all font-mono text-caption text-faint">
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
                <span className="block max-w-[70ch] text-meta leading-relaxed text-muted">
                  {item.desc}
                </span>
              </div>
            </li>
          ))}
        </ul>

        {/* The extras, in the same tree rather than a second box: they are entries in the one
            archive, and giving them their own bordered card would say "a separate thing you may
            also get". The label is what separates them, because the difference is real and a buyer
            is entitled to it -- the eight above are audited on every pack before it may be listed,
            these ride along. */}
        <div className="border-t border-border bg-surface2 px-5 py-2">
          <span className="font-mono text-caption text-subtle">also in the download</span>
        </div>
        <ul className="list-none p-0">
          {PACK_EXTRAS.map((item, i) => (
            <li key={item.filename} className="border-b border-border/60 px-5 py-4 last:border-b-0">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                <span aria-hidden className="flex-none font-mono text-caption text-faint">
                  {i === PACK_EXTRAS.length - 1 ? '└──' : '├──'}
                </span>
                <span className="min-w-0 text-meta font-semibold leading-snug text-text">
                  {item.title}
                </span>
                <span className="min-w-0 break-all font-mono text-caption text-faint">
                  {item.filename}
                </span>
              </div>
              <div className="pl-[3.25rem]">
                <span className="block max-w-[70ch] text-meta leading-relaxed text-muted">
                  {item.desc}
                </span>
              </div>
            </li>
          ))}
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
          what you are buying.

          "plain-text" came out on 2026-08-14, when it stopped being true: bridge.py now also
          writes Complete_Pack.pdf, a typeset edition of the whole pack, and a buyer told "plain
          text" who opens a PDF has been told something false about the thing they paid for. It is
          also the one addition worth the words. The founder's verdict on the pack as shipped was
          that "markdown files is not the one"; the PDF is the answer to that, and a feature the
          shelf does not mention is a feature nobody buys. The count still counts DELIVERABLES,
          not archive entries, which is why the noun beside it stays "documents". */}
      <div className="mt-4 flex flex-col gap-3 rounded-md border border-border bg-surface2 p-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-[62ch] text-meta text-muted">
          <span className="font-medium text-text">{PACK_CONTENTS.length} documents, 5,000+ words,
          in Markdown you can edit and one typeset PDF you can print.</span>{' '}
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
