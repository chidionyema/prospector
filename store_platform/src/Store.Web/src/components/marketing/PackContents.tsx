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
 * So the note is replaced by a mechanism, and `__tests__/packContents.test.ts` reads the tuples
 * out of the Python source and asserts these lists match them. Changing the bundle without telling
 * buyers now fails `npm test`.
 *
 * ── 2026-08-15: the split ──
 * Until now this file had ONE list, because the engine had one tuple doing two jobs: `BUNDLE_FILES`
 * was simultaneously the sellability contract and the list of documents. The founder's verdict on
 * the shipped pack was "why do we need 14 files? ... i dont like md files at all, we are not
 * selling to developers", and the answer measured across the 59 live packs was that the eight
 * Markdown files were duplicates: 0 of 853 headings, 0 of 208 table cells and 0 of 6,743 prose runs
 * in them were absent from the rendered `index.html`. They were the render INPUT, shipped by
 * accident alongside the render OUTPUT.
 *
 * So bridge.py now splits them (`PACK_DOCUMENTS` = what gets written, `BUNDLE_FILES` = what the
 * archive must contain) and this file splits the same way:
 *
 *   PACK_DOCUMENTS -- the documents a buyer READS. Sections of the reader, not files any more.
 *                    Pinned in order to `bridge.py::BUNDLE_READING_ORDER`, which as of the
 *                    2026-08-15 narrative restructure is a literal tuple of fourteen and is read
 *                    out of the Python source directly by the drift test. The order is the
 *                    buyer's journey, not the order the engine happens to compose things in.
 *   PACK_CONTENTS  -- the five files the download CONTAINS. Pinned in order to `BUNDLE_FILES`.
 *   PACK_EXTRAS    -- the rest of the archive, deliberately not promises. Pinned to
 *                    `BUNDLE_BONUS_FILES`.
 *
 * The buyer receives no less writing than before; they receive it in a form that opens. Nothing in
 * PACK_DOCUMENTS was deleted from the product, only from the file listing.
 *
 * The other half of the guarantee is engine-side: `bridge.py` re-audits the written zip and ANDs
 * the result into `is_listed`, so a pack missing any file in PACK_CONTENTS cannot be listed for
 * sale. Note what that now means: the PDF, the reader, the card and the CSV are contract, so a
 * renderer failing takes the pack OFF the shelf rather than shipping it quietly short.
 *
 * Word and link floors are measured, not aspirational: across the bundles live on 2026-07-27 the
 * smallest was 5,069 words and the smallest link count 23 (median 7,523 / 119). The floor has to
 * be true of the weakest pack, not the best one.
 *
 * The `emoji` field is deleted (brand v3, 2026-08-06). Eight emoji stacked down a list render as
 * eight different pieces of third-party artwork -- a different set on macOS, Windows and Android --
 * on the one screen whose job is to look like a document worth £49. The file icon is now a single
 * consistent glyph from our own set.
 */
export const PACK_DOCUMENTS: {
  title: string;
  /**
   * The engine-side document this section is composed from. Pinned to BUNDLE_READING_ORDER by the
   * drift test. NOT shown to buyers: it is a `.md` name, and these no longer arrive as files.
   */
  section: string;
  desc: string;
  /** Appends the pack's real cited-source count. Only the QA report earns it. */
  showSourceCount?: boolean;
}[] = [
  // --- the opening: the situation, then the promise of the piece ---
  {
    title: 'Where this starts',
    section: '00_Executive_Summary.md',
    desc:
      'The opportunity on one page: what it is, what checked out, and what we do not claim.',
  },
  {
    title: 'What you would be selling',
    section: 'The_Offer.md',
    desc:
      'The thing that changes hands for money, written as an offer a buyer could accept today.',
  },
  {
    title: 'The field: who is already there',
    section: 'The_Field.md',
    desc:
      'The people already selling into this, what they charge, and where they leave the door open.',
  },
  // --- the stakes, before the instructions ---
  {
    title: 'The numbers',
    section: '04_Financial_Model.md',
    desc:
      'Pricing and the numbers behind it. Anything we could not verify is marked missing, never made up.',
  },
  {
    title: 'What would sink this',
    section: 'What_Would_Sink_This.md',
    desc:
      'The case against, at full strength, so you meet the objection here rather than from a customer.',
  },
  // --- the body: how it is done ---
  {
    title: 'What you build',
    section: '01_Blueprint_BuildSpec.md',
    desc:
      'What to build, in what order, on what stack. Includes the non-goals for v1 and what would kill this.',
  },
  {
    title: 'How the first customers find you',
    section: '02_Marketing_Plan_GTM.md',
    desc:
      'Where your first customers come from. Named channels, the beachhead to start in, and the signals that say stop.',
  },
  {
    title: 'How it runs once it works',
    section: '03_Operations_Plan.md',
    desc:
      'How it runs once someone pays. Delivery, capacity limits, the compliance you cannot skip, and where the manual work sits.',
  },
  {
    title: 'Your first fortnight',
    section: '05_First_Week_Checklist.md',
    desc:
      'Six steps for days one to seven: confirm the buyer, size the smallest paid offer, pick one channel.',
  },
  // --- the things a buyer uses rather than reads ---
  {
    title: 'The toolkit',
    section: 'The_Toolkit.md',
    desc:
      'The named tools, services and suppliers this runs on, with what each one is actually for.',
  },
  {
    title: 'Copy you can paste',
    section: 'Marketing_Assets.md',
    desc:
      'Launch copy you can send today: listing page, outreach, social. Claim-checked like the research.',
  },
  // --- the kicker: what resolves it ---
  {
    title: 'How to know in 30 days',
    section: 'How_To_Know_In_30_Days.md',
    desc:
      'The one month test: what to run, what number to watch, and the reading that says walk away.',
  },
  // --- appendix: the receipts ---
  {
    title: 'Everything we read, once',
    section: 'Evidence_and_Constraints.md',
    desc:
      'Each check, what it found, and the source behind it, without hunting through the plans.',
  },
  {
    title: 'Every check, in full',
    section: 'QA_Report.md',
    showSourceCount: true,
    desc:
      // Not "all six checks": the check set is lane-dependent, so this file carries eight or
      // nine verdicts on the packs vetted by the side-hustle lanes. The claim that is true of
      // every pack is "every check that was run, with its verdict and its source".
      'Every check this pack faced, each verdict, and a clickable source behind every claim.',
  },
];

/**
 * What the download actually contains. Pinned in order to `bridge.py::BUNDLE_FILES`.
 *
 * Every one of these is a sellability CONTRACT: `audit_bundle` iterates this tuple and `is_listed`
 * is ANDed with its result, so a pack missing one cannot go on the shelf. That is why the list is
 * short and why nothing speculative belongs in it.
 *
 * These are formats, not extra content -- the same documents, rendered four ways for four
 * situations (read, print, work from, open in a spreadsheet), plus the one file a buyer EDITS.
 * Marketing_Assets.txt stays plain text for exactly that reason: it is copy to paste, and asking
 * someone to extract paragraphs out of a PDF to send an email is the developer-artefact problem in
 * miniature.
 */
export const PACK_CONTENTS: { title: string; filename: string; desc: string }[] = [
  {
    title: 'The pack, readable',
    filename: 'index.html',
    desc: 'Open this first and read the whole pack in order in your browser. No install, no account.',
  },
  {
    title: 'The pack, typeset for print',
    filename: 'Complete_Pack.pdf',
    desc: 'Every document in one printable PDF. Open it on a phone, or put it in front of someone.',
  },
  {
    title: 'Your first fortnight, on one page',
    filename: 'First_Fortnight.html',
    desc: 'A single sheet to print and work from. Days one to fourteen, nothing else on it.',
  },
  {
    title: 'Every assumption, as a spreadsheet',
    filename: 'Assumptions.csv',
    desc: 'Every number the financial model rests on, in a file your spreadsheet opens directly.',
  },
  {
    title: 'Marketing copy, ready to paste',
    filename: 'Marketing_Assets.txt',
    desc: 'The launch copy as plain text, so it goes straight into an email, a listing or a post.',
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
 * The extras were invisible here until 2026-08-14, and that was the actual complaint. The bundle
 * grew a typeset PDF, a printable first-fortnight sheet, a machine-readable assumptions table, the
 * evidence stated once, and a rendered reader (commit 40212a3); the shelf went on describing eight
 * Markdown files, so the one answer to "markdown files is not the one" was shipped to buyers and
 * advertised to nobody. A feature the shelf does not mention is a feature nobody buys. Four of
 * those five have since been promoted into the contract above; the manifest stays here because a
 * missing machine-readable index is not a reason to refuse a buyer a pack.
 */
export const PACK_EXTRAS: { title: string; filename: string; desc: string }[] = [
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
       * The glyphs are literal box-drawing characters rather than borders or an SVG, because at
       * `text-caption` in the mono face they align on the same grid the titles do. They are
       * inside an `aria-hidden` span: a screen reader announcing "box drawings light up and right"
       * before every line is noise, and the `<ul>`/`<li>` structure already carries "this is a
       * list" losslessly.
       *
       * 2026-08-15: the filenames come OFF the document rows. They were kept there through two
       * redesigns on a good argument -- a real zip entry a buyer can check against their download
       * is falsifiable in a way another adjective is not -- but that argument only holds while the
       * name IS an entry in the download. These are sections of the reader now, so printing
       * `00_Executive_Summary.md` beside one would be the rarest kind of drift: a filename that is
       * true of our source tree and false of the product. The falsifiable-listing argument is not
       * abandoned, it MOVES: the second group below lists the five real entries, and those a buyer
       * can still check one for one against the zip.
       *
       * The root is NOT a zip filename. `bridge.py:813` writes `prospector_pack_<id8>.zip` locally
       * while the delivery key at `:632` is `packs/<id>/<content_hash>.zip`, so which of those a
       * buyer's browser saves is not a fact this component can state. It states the fact it has.
       */}
      <div className="mt-6 overflow-hidden rounded-md bg-surface">
        <div className="flex items-center gap-2 border-b border-border bg-surface2 px-5 py-3">
          <Icon name="download" size={14} className="flex-none text-subtle" />
          {/* Sans, and words. This read `your pack/` in mono -- a directory name, drawn with
              box-drawing glyphs below it, on a page selling finished documents to a non-developer.
              The falsifiable half of that design (the real filenames, second group) is kept; the
              costume around it is not. Founder, 2026-08-15: "the full contents styling and design
              is poor". */}
          <span className="text-caption font-medium text-text">Inside the pack</span>
          {/* "documents", not "files", and the two are now DIFFERENT NUMBERS rather than the same
              number under a careful noun: `PACK_DOCUMENTS.length` documents arrive as
              `PACK_CONTENTS.length` files -- 14 and 5 as counted on 2026-08-15, and written as the
              expressions rather than the digits because the last version of this note said "Nine
              documents arrive as five files" while the code beside it rendered 14. A comment that
              hardcodes what the line below derives goes stale silently and then misinforms the
              next reader about which number is load-bearing. Until 2026-08-15
              this count read `PACK_CONTENTS.length` and the noun had to do the work of hiding that
              the archive held more entries than the list showed (measured 2026-08-08 across the 45
              packs then live: 8 entries on 12 packs, 9 on 14, 10 on 19, against a stated eight).
              Now each count is rendered next to the thing it counts and neither has to be careful:
              this one counts what you read, the group below counts what you receive. */}
          <span className="ml-auto font-mono text-caption text-subtle">
            {PACK_DOCUMENTS.length} documents
          </span>
        </div>
        <ul className="list-none p-0">
          {PACK_DOCUMENTS.map((item, i) => (
            <li key={item.section} className="border-b border-border/60 px-5 py-4">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="min-w-0 text-meta font-semibold leading-snug text-text">
                  {item.title}
                </span>
                {hasCount && item.showSourceCount && (
                  <span className="flex-none font-mono text-caption text-success">
                    {sourceCount} sources
                  </span>
                )}
              </div>
              {/* Flush left. This was `pl-[3.25rem]`, hanging the prose off the tree glyph that no
                  longer exists; with the glyph gone the indent was decoration measuring nothing. */}
              <div className="mt-1">
                <span className="block max-w-[70ch] text-meta leading-relaxed text-muted">
                  {item.desc}
                </span>
              </div>
            </li>
          ))}
        </ul>

        {/* The files, in the same card rather than a second box: they are one archive, and giving
            them their own bordered card would say "a separate thing you may also get". The label is
            what separates them, because the difference is real and a buyer is entitled to it --
            above is what the pack SAYS, here is what lands in the folder. Every entry in the first
            of these two groups is audited on every pack before it may be listed. */}
        <div className="border-t border-border bg-surface2 px-5 py-2">
          <span className="font-mono text-caption text-subtle">
            arrives as {PACK_CONTENTS.length} files
          </span>
        </div>
        <ul className="list-none p-0">
          {[...PACK_CONTENTS, ...PACK_EXTRAS].map((item, i, all) => (
            <li key={item.filename} className="border-b border-border/60 px-5 py-4 last:border-b-0">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="min-w-0 text-meta font-semibold leading-snug text-text">
                  {item.title}
                </span>
                <span className="min-w-0 break-all font-mono text-caption text-faint">
                  {item.filename}
                </span>
              </div>
              <div className="mt-1">
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
          the £49 purchase sound like a developer artefact rather than finished documents.

          The Notion and Obsidian name-drops are GONE. They were two brands most readers do not
          use, spent to make one point ("it opens anywhere") that "paste anywhere" makes without
          asking anyone to recognise a product.

          2026-08-14 took out "plain-text", when bridge.py started writing a typeset PDF and the
          phrase stopped being true. 2026-08-15 takes out "Markdown you can edit" for the same
          reason in the other direction: the Markdown no longer ships. What replaces it is not a
          softer claim but a more specific one -- read, print, open in a spreadsheet, paste -- which
          is what the founder was asking for when the objection was "we are not selling to
          developers". The count beside the words counts DOCUMENTS, which is why the noun is
          "documents"; the files are counted in the tree above, where they are listed. */}
      <div className="mt-4 flex flex-col gap-3 rounded-md border border-border bg-surface2 p-6 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-[62ch] text-meta text-muted">
          <span className="font-medium text-text">{PACK_DOCUMENTS.length} documents, 5,000+ words,
          as a web page you can read, a PDF you can print and a spreadsheet you can open.</span>{' '}
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
