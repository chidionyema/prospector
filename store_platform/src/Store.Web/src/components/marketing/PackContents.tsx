import React from 'react';

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
      'What to build, in what order, and what to build it with. Includes what to leave out at first and what would kill this.',
  },
  {
    title: 'How the first customers find you',
    section: '02_Marketing_Plan_GTM.md',
    desc:
      'Where your first customers come from. Named channels, the first group to sell to, and the signals that say stop.',
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
      'Launch copy you can send today: listing page, outreach, social. Checked against the sources, like the research.',
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
    title: 'A version other software can read',
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
  const files = [...PACK_CONTENTS, ...PACK_EXTRAS];
  return (
    <div className={className}>
      {/*
       * THE DRAWING'S SHAPE (`mockups/index.html:563`, section 15 "THE FULL CONTENTS").
       *
       * This rendered as one bordered card holding twenty stacked rows: fourteen documents down a
       * single column, then six files down the same column. On a 1440px screen that is roughly
       * 2,000px of list where the drawing spends about 700px, and it was most of the reason the
       * home page ran 4,000px longer than the drawing. Founder, 2026-08-18: "is different fron
       * nockups".
       *
       * The drawing splits it in two and uses the width: `.docs` is a two-column grid of numbered
       * `.docitem` rows (mumchimp.css), `.files` is a three-column grid of `.file` cards
       * (mumchimp.css), and a `.files-note` row closes it with the format sentence and the
       * "Instant download" pill. Same content, same order, same words. Nothing was dropped: the
       * per-pack source count still rides on the QA document, and every filename is still printed
       * so a buyer can check it against their zip.
       */}
      <div className="sechead">
        <h2 className="sec">{heading}</h2>
        {/* Two counts, each next to the thing it counts, exactly as the drawing prints them.
            Derived, never typed: the numbers move when the tuples move. */}
        <span className="mono num">
          {PACK_DOCUMENTS.length} documents · {files.length} files
        </span>
      </div>
      {lead && <p className="lede">{lead}</p>}

      <div className="docs">
        {PACK_DOCUMENTS.map((item, i) => (
          <div key={item.section} className="docitem">
            <span className="i num">{String(i + 1).padStart(2, '0')}</span>
            <div>
              <h5>
                {item.title}
                {hasCount && item.showSourceCount && (
                  <span className="ml-2 font-mono text-caption font-normal text-success">
                    {sourceCount} sources
                  </span>
                )}
              </h5>
              <p>{item.desc}</p>
            </div>
          </div>
        ))}
      </div>

      <p className="eyebrow mt-[34px]">What lands in your folder</p>
      <div className="files">
        {files.map((item) => (
          <div key={item.filename} className="file">
            <p className="fn">{item.filename}</p>
            <h5>{item.title}</h5>
            <p>{item.desc}</p>
          </div>
        ))}
      </div>
      <div className="files-note">
        <p>
          A web page you can read, a PDF you can print and a spreadsheet you can open. Yours to
          keep, edit, or paste anywhere. No login, no subscription.
        </p>
        <span className="pillx">Instant download</span>
      </div>
    </div>
  );
}
