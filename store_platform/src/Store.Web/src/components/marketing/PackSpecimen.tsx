import Link from 'next/link';

import report from '@/data/sample-report.json';
import { PACK_DOCUMENTS } from '@/components/marketing/PackContents';
import { plainEnglish } from '@/lib/plainEnglish';
import { Button, Icon, SourceChip, sourceHost } from '@/components/ui';

/**
 * ONE PAGE OF THE PRODUCT, SHOWN.
 *
 * THE FEAR THIS EXISTS TO KILL. The single biggest objection on a digital download page is
 * "£49 for a two-page Google Doc". Until now this section answered it with a manifest -- nine
 * titles and a sentence under each. A list of nouns is a CLAIM about contents; it asks to be
 * believed. A page you can read is EVIDENCE; it asks to be checked. The founder's verdict on the
 * manifest as the section's hero was "underwhelming... show not tell", and the manifest is not
 * deleted for it -- it moves below this, where a list of contents belongs once the thing has been
 * seen.
 *
 * WHY THIS PAGE AND NOT A PRETTIER ONE. The page rendered here is the one carrying the pack's
 * FAILED check. Eight green ticks read as marketing; one refutation reads as a document. Nobody
 * fabricates a flaw in their own product, so a visible failure is the cheapest credibility this
 * shop will ever buy -- and it costs nothing, because `sample-report.json` already ships with
 * `claims_verifiable: "refuted"` in it. The choice is not hardcoded: `FAILED` is the first
 * non-`supported` check the data contains, and NO COPY anywhere states which page was chosen or
 * why. That reasoning is ours; saying it out loud to a buyer is a shop explaining its own
 * merchandising, which is what the founder rejected on 2026-08-15. Re-generate the sample with
 * eight clean checks and the sheet simply prints that check's verdict, with nothing to retract.
 *
 * WHY IT REPLACES `EvidenceRecordPanel`. That component rendered these same eight verdicts, in
 * this same section, under the eyebrow "A real page from a real pack" -- while looking like a web
 * table. It made the claim this makes and could not back it, and two evidence objects 200px apart
 * is the "same paragraph four times" defect this whole pass exists to remove. The content is not
 * lost: the record's SHAPE is still in the hero (`HeroEvidenceStrip`, eight marks and a count) and
 * its full CONTENT is one click away on /sample, which is where the CTA below points and where a
 * reader who wants all eight rows should be reading them anyway.
 *
 * WHAT MAKES IT READ AS PAPER RATHER THAN AS A CARD. Four things, in order of how much work they
 * do:
 *
 *   1. It is CROPPED BY ITS OWN FRAME, and it begins mid-sentence. A full small preview says
 *      "this is all there is". A page whose first line is the tail of the previous page's
 *      paragraph, and whose bottom edge cuts through the next section, says "this continues"
 *      without printing a number or a promise. The continuation text is real: it is the closing
 *      clause of the check immediately before the failed one, quoted with a leading ellipsis the
 *      way any document quotes a continuation.
 *   2. A RUNNING HEAD -- the pack's title on the left, the section on the right, a hairline under
 *      both. The section name is read from `PACK_DOCUMENTS`, so the page cannot claim to belong to
 *      a document the manifest below it does not list.
 *   3. REAL MARGINS at document proportions, and a measure near 62 characters. The margins are
 *      what separate a typeset page from a padded div, and they are the reason this component
 *      does not reuse `Card`.
 *   4. ONE COLOURED WORD on the entire sheet. Everything else is ink. `--warning-strong` on
 *      `--warning-bg` (6.84:1) rather than red, because tokens.css reserves red and green for
 *      exactly one meaning each -- killed and survived -- and a check that pushed back on a pack
 *      that SURVIVED is neither. /sample already draws this identical state the same way.
 *
 * NO SHADOW, ANYWHERE. The obvious way to draw stacked paper is a soft drop-shadow, and this
 * design system forbids it: `--shadow-1`/`--shadow-2` are `none` (tokens.css:329-330) and the
 * comment above them states the rule -- borders draw edges here, and a shadow may only ever mean
 * "this element is physically above the page" (a hover lift, a modal). So the stack is drawn the
 * way the system draws everything else: two more hairline-bordered white rectangles, offset a few
 * pixels. It reads as thickness because the edges are real, not because they are blurred.
 *
 * NO ACCORDION, and no "expand to read more". Progressive disclosure has already made a guard test
 * vacuous on this site once (memory: `progressive-disclosure-makes-a-guard-test-vacuous`), and the
 * fade is doing the same job honestly: the way to read the rest is the free sample, which is the
 * only call to action here.
 *
 * MOBILE. The crop height is set so that the running head, the continuation line, the section
 * heading with its verdict, and at least three lines of body prose all sit ABOVE the fade at
 * 360px. Below that floor the object stops reading as a page and starts reading as a decorative
 * box, which is the failure mode this replaces.
 */

type Source = { url: string; label: string };
type Check = {
  name: string;
  key: string;
  verdict: string;
  confidence: number;
  rationale: string;
  sources: Source[];
};

const CHECKS = report.checks as Check[];

/**
 * The failed check, found rather than named. The fallback keeps the component renderable against a
 * sample where everything passed: the sheet then prints that check's own verdict word instead, so
 * the specimen degrades to an honest page rather than to a claim about a failure that isn't there.
 * Nothing here narrates the choice to the reader -- the page is the evidence, not the caption.
 */
const FAILED_INDEX = CHECKS.findIndex((check) => check.verdict !== 'supported');
const FAILED = FAILED_INDEX >= 0 ? CHECKS[FAILED_INDEX] : CHECKS[CHECKS.length - 1];
const PAGE_NUMBER = (FAILED_INDEX >= 0 ? FAILED_INDEX : CHECKS.length - 1) + 1;

/** The check printed immediately above this one, for the mid-sentence opening. */
const PRECEDING = CHECKS[Math.max(0, (FAILED_INDEX >= 0 ? FAILED_INDEX : CHECKS.length - 1) - 1)];

/**
 * The tail of a sentence, cut at a word boundary -- the fragment a page inherits from the page
 * before it. Deliberately not a character slice: cutting mid-word would read as a rendering bug
 * rather than as a continuation, which is the entire effect being bought here.
 */
function sentenceTail(text: string, maxChars = 96): string {
  const clean = (text ?? '').trim();
  if (clean.length <= maxChars) return clean;
  const window = clean.slice(clean.length - maxChars);
  const space = window.indexOf(' ');
  return space === -1 ? window : window.slice(space + 1);
}

/**
 * A source's own page slug, read back as words.
 *
 * The engine ships `label: ""` on every source in this report (checked 2026-08-16: all 6 sources on
 * the failed check, all 6 on the premortem), so a footnote list drawn from `label` would be six
 * blank lines, and one drawn from the host alone repeats itself -- two of the six are the same law
 * firm's site, and "gowlingwlg.com" twice reads as a rendering fault rather than as two articles.
 * The slug is the publisher's own words for their own page, sitting in the URL the reader can open
 * and check. It is not generated, summarised or inferred; if the path carries nothing usable this
 * returns empty and the row is just the link.
 */
function slugTitle(url: string): string {
  try {
    const last = new URL(url).pathname.split('/').filter(Boolean).pop() ?? '';
    const words = decodeURIComponent(last)
      .replace(/\.(html?|php|aspx?|pdf)$/i, '')
      .replace(/[-_+]+/g, ' ')
      .trim();
    // Short tails ("uk", "p", "238884") are route furniture, not a title.
    if (words.length < 16) return '';
    return words.charAt(0).toUpperCase() + words.slice(1);
  } catch {
    return '';
  }
}

/** The section of the pack this page belongs to, read from the manifest so it cannot drift. */
const SECTION_TITLE =
  PACK_DOCUMENTS.find((doc) => doc.section === 'Evidence_and_Constraints.md')?.title ??
  'Evidence and Constraints';

export function PackSpecimen({ className }: { className?: string }) {
  const source = FAILED?.sources?.[0];
  /** Footnote 1 is printed on the sheet; 2..n are the column's job. */
  const restSources = (FAILED?.sources ?? []).slice(1);

  return (
    <div className={className}>
      {/* THE COMPOSITION. Argument on the left, object on the right, and the object spans both of
          the left column's rows so its bottom edge and the CTA's baseline land together. The
          earlier version stacked them -- a narrow column of copy with 700px of empty page beside
          it, then a wide grey box with a small sheet marooned in the middle of it. The specimen
          was the smallest thing in a section that exists to make it the largest.

          The row/column placement is explicit rather than implicit because DOM ORDER IS THE MOBILE
          ORDER: heading, then the page, then the price argument and the button. A reader on a
          phone must meet the product before the ask, and `lg:row-start-*` is what lets the desktop
          composition disagree with that without reordering the source. */}
      {/* `min-w-0` on the grid and on every child, because a GRID ITEM'S DEFAULT `min-width` IS
          `auto`, not zero: the track refuses to shrink below its content's min-content width. The
          sheet's running head sets a wide min-content, so at 320px this whole section measured 357px
          inside a 320px viewport (2026-08-15) -- the eyebrow, the headline, the counts line and the
          right-hand edge of the page itself all ran past the screen. It never showed up as a
          horizontal scrollbar because an ancestor is `overflow-x: clip`, so the page LOOKED fine and
          simply cut the content off. That is the worst version of this bug: silent. `min-w-0` lets
          the track shrink to the viewport and the truncation inside the sheet do its job. */}
      {/* THE LEFT COLUMN IS SHORTER THAN THE SHEET, AND THE ANSWER IS CONTENT, NOT GEOMETRY. Two
          founder reports, one defect, both about the same slack:

            "why the blank in the middle?"  the column was `auto 1fr` with the bottom block
                                            `self-end`, so the slack sat BETWEEN the counts line
                                            and the quote. Moved to the foot of the column.
            "why is panel empty"            the slack was still there, now in one piece under the
                                            button -- which is what a reader was looking at.

          Measured on the built page at 1440x900 and 1280x800 (identical; the grid caps at 1200px):
          the section is 686px tall because the right column is, and the left column held 121px +
          56px gap + 194px = 371px. 315px, 46% of the section's height, was empty. Both attempts
          before this one MOVED that space; the founder's instruction was to put actual relevant
          content in it, which is the right call -- the previous two fixes were both arrangements
          of nothing.

          What went in is the rest of this page's footnote apparatus (see below). What was rejected:
          shrinking the sheet, because at 30rem the fade begins at 352px against a body paragraph
          that ends near 465px, the exact "fade lands mid-prose" defect the mobile floor was raised
          to fix; and stacking the composition, which is the arrangement the top of this comment
          records as already tried. */}
      <div className="grid min-w-0 gap-10 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:grid-rows-[auto_1fr] lg:gap-14">
        <div className="min-w-0 lg:col-start-1 lg:row-start-1">
          {/* The eyebrow is SANS. The wide-tracked all-caps mono eyebrow is the exact pattern
              `__tests__/monoIsTheDataVoice.test.ts` was written to stop spreading: mono is the
              evidence voice -- amounts, IDs, hostnames, scores -- and "a page from the free
              sample" is human language. The mono in this component is spent on the three things a
              reader could transcribe: the check counter, the confidence figure and the caption
              rail's counts. (That test reads raw source lines, so naming those utilities together
              in a comment is itself an offence -- which is why this spells them out in words.) */}
          <p className="eyebrow">A page from the free sample</p>

          {/* The headline states the SCALE and then immediately stops asserting it, which is the
              whole argument of the section in one move: the number answers "is this a two-page
              Google Doc?", and the page beside it answers "prove it". */}
          <h2 className="mt-2 sec">
            {PACK_DOCUMENTS.length} documents. Here is one page of one of them.
          </h2>

          {/* THE MEASUREMENTS. In the ARGUMENT column, not under the object, because they are the
              numeric half of the same answer: the page beside them settles "is this real writing?"
              and the word count settles "is there enough of it?". Mono, because every one of these
              is a figure a reader can check against the pack itself. The document COUNT is not
              here: the headline two lines up already owns it, and `__tests__/factOwnership.test.ts`
              exists because this site kept stating the same number twice in one breath. */}
          <p className="mt-6 font-mono text-caption text-subtle">
            {CHECKS.length} checks · {report.sourceCount} sources · 5,000+ words
          </p>
        </div>

        <div className="min-w-0 lg:col-start-2 lg:row-start-1 lg:row-span-2">
          {/* THE PLINTH. `--surface3` behind white paper is what makes the paper read as paper; on
              the page's own white it would read as a bordered div. It HUGS the sheet -- the grey is
              a margin, not a stage. The padding is asymmetric because the stack is offset down and
              right and must not touch the plinth's edge. */}
          {/* ONE PADDED CONTAINER BELOW 640px (founder review, 2026-08-15, measured at 390).
              The plinth, the stack offset and the document margins each contributed their own
              horizontal padding, and they compounded: 16+16 (plinth `p-4`) + 12 (`pr-3`) + 24+24
              (`px-6`) = 92px of nested chrome inside a 342px frame, leaving the excerpt a 246px
              text column -- 63% of the viewport, a realised measure of 27 characters, and prose
              wrapping at four or five words a line.

              Three of the four contributors are DECORATION -- the grey ground, the border and the
              two offset sheets underneath all exist to make the sheet read as paper laid on a
              surface. On a phone there is no room for a surface to be visible around the paper
              anyway: 16px of grey either side reads as a stray border, not as a plinth. So below
              `sm` the plinth stops painting entirely and the article keeps only its own document
              margin. The composition from `sm` up is byte-identical -- every class that was here
              is still here behind an `sm:` prefix. */}
          <div className="rounded-md sm:border sm:border-border sm:bg-surface3 sm:p-8">
            <div className="relative sm:pb-3 sm:pr-3">
              {/* THE SHEETS UNDERNEATH: two, not three -- at three the offsets start reading as a
                  deliberate graphic rather than as a stack that happens to be there. They are
                  `aria-hidden` and carry no text: a screen reader gets the page once. */}
              <div
                aria-hidden
                className="absolute left-3 top-3 hidden h-full w-full rounded-sm border border-border bg-surface sm:block"
              />
              <div
                aria-hidden
                className="absolute left-1.5 top-1.5 hidden h-full w-full rounded-sm border border-border bg-surface sm:block"
              />

              {/* THE PAGE. `overflow-hidden` is the crop; nothing inside it is sticky (that
                  combination silently kills every descendant sticky -- memory:
                  `overflow-hidden-kills-every-descendant-sticky`). The heights are the mobile floor
                  described in the docblock, measured to keep four elements above the fade at
                  360px.

                  THE MOBILE FLOOR WENT 29rem -> 36rem (2026-08-15). At 29rem the fade began at
                  384px and the clamped body paragraph ends at ~484px, so the fade started BEFORE
                  the prose it was supposed to follow -- the sheet showed three lines of argument
                  and then dissolved, which reads as a broken box rather than as a page continuing
                  past its frame. 36rem puts the whole clamped paragraph above the fade and leaves
                  the fade something real to dissolve: the footnote and its cited source. */}
              <article className="relative max-h-[36rem] overflow-hidden rounded-sm border border-border bg-surface sm:max-h-[38rem]">
                {/* DOCUMENT MARGINS, not card padding. Wider at the sides than a card would be,
                    and the type inside runs to a ~62ch measure rather than to the container. */}
                <div className="px-5 pb-10 pt-7 sm:px-12 sm:pb-14 sm:pt-11">
                  {/* THE RUNNING HEAD. Sans, because both halves are titles -- human language. The
                      hairline under it is the single most "this is a typeset page" signal
                      available for one border-width of cost. */}
                  {/* THE RUNNING HEAD STACKS ON A PHONE, and that is a fix for lost information
                      rather than a layout preference (founder review, 2026-08-15).

                      The two halves shared the row by CONTENT LENGTH, not by fraction: the title
                      was `min-w-0 truncate` (flex `0 1 auto`, so it shrinks) and the section
                      label was `flex-none` (so it never does). Every pixel of shortfall was
                      therefore charged to the one half that carries information. Measured at
                      390px: the title rendered 94px wide as "The S…" -- an ellipsis with no
                      content in front of it -- while its sibling "Everything we read, once", a
                      constant string that is the same on every pack, rendered whole at 137px.

                      Equal fractions would only move the damage: at 143px each, the static label
                      truncates too and the title still loses most of itself. A running head is
                      two lines' worth of text and one line's worth of room, so it gets two lines.
                      Stacked, the title has the full measure and NEITHER half truncates. The `sm`
                      row is unchanged. */}
                  <div className="flex flex-col gap-1 border-b border-border pb-3 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                    <span className="min-w-0 truncate text-caption font-medium text-text">
                      {report.title}
                    </span>
                    <span className="min-w-0 truncate text-caption text-subtle sm:flex-none">
                      {SECTION_TITLE}
                    </span>
                  </div>

                  {/* THE MID-SENTENCE OPENING. Real text: the closing clause of the check printed
                      immediately before this one, quoted with a leading ellipsis. This is the line
                      that does the "there are pages before this one" work, and it does it without
                      claiming a page count we cannot substantiate. */}
                  {/* LEADING IS TIED TO THE REALISED MEASURE, not to the one `max-w-[62ch]`
                      names (founder review, 2026-08-15). That cap is 571px and has never bound on
                      a phone: the column is ~302px after the collapse above, so the measure is
                      about 33 characters. 1.75 is the correct ratio for 62ch and is far too open
                      for 33 -- short lines set that loosely stop reading as a paragraph and start
                      reading as a list of disconnected fragments, which is exactly what the
                      founder saw. 1.5 below `sm`, 1.75 from `sm` up where the 62ch cap does bind
                      and the ratio it was chosen for is the ratio in effect. */}
                  <p className="mt-6 max-w-[62ch] leading-[1.5] sm:leading-[1.75] lede">
                    …{sentenceTail(plainEnglish(PRECEDING?.rationale ?? ''))}
                  </p>

                  {/* THE SECTION HEADING, numbered the way a document numbers itself. The counter
                      is mono -- it is a figure a reader could compare against the eight marks in
                      the hero and against the pack's own QA report. */}
                  <div className="mt-8 flex flex-wrap items-baseline gap-x-3 gap-y-2 border-t border-border pt-6">
                    <span className="flex-none font-mono text-caption text-subtle">
                      {PAGE_NUMBER} of {CHECKS.length}
                    </span>
                    <h3 className="min-w-0 flex-1 leading-snug sub">
                      {FAILED?.name}
                    </h3>
                  </div>

                  {/* THE ONE COLOURED WORD ON THE SHEET. Amber, never red: red and green are
                      reserved for killed and survived, and this pack SURVIVED with a check that
                      pushed back. Spending red here would spend the signal the kill log needs. */}
                  <p className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    {/* The caps are in the VALUE, not in a class.
                        `__tests__/weightAndCasePolicy.test.ts` bans `text-transform` outright: a
                        CSS-uppercased string is copied, read aloud and indexed in its original
                        case, so the caps exist only for sighted readers and the markup and the
                        screen disagree about what the page says. */}
                    <span className="rounded-sm border border-warning-strong bg-warning-bg px-2 py-0.5 text-caption font-semibold tracking-wide text-warning-strong">
                      {(FAILED?.verdict ?? '').toUpperCase()}
                    </span>
                  </p>

                  {/* THE BODY, at document scale: `text-body` with 1.75 leading and a 62ch measure.
                      This is the paragraph that has to survive being read closely, which is why it
                      is the report's own words and not a description of them.

                      `line-clamp-5` ON MOBILE ONLY, and it is a fix for the crop below rather than
                      a decision about this paragraph. Measured at 390px on 2026-08-15: the running
                      head, the quoted tail, the numbered heading and the REFUTED badge consume
                      ~344px of the 29rem sheet, which leaves about four lines for this paragraph --
                      so the fade landed in the MIDDLE OF IT and took the word `there` in half.
                      That is not the effect the frame is going for. The cut is meant to fall on the
                      section below ("the strongest case against this idea"), where a document
                      visibly arguing with itself is the point; on a phone that section was never
                      reached, so all a reader got was a sentence amputated by a gradient.

                      A clamp ends on a WORD boundary and appends its own ellipsis, so the last
                      thing a phone reader sees is a complete clause that stops, rather than a word
                      dissolving. `sm:line-clamp-none` because from `sm` up the sheet is 38rem and
                      the paragraph fits whole -- the desktop composition is unchanged. */}
                  <p className="mt-5 line-clamp-5 max-w-[62ch] text-body leading-[1.5] text-text sm:line-clamp-none sm:leading-[1.75]">
                    {plainEnglish(FAILED?.rationale ?? '')}
                  </p>

                  {/* THE FOOTNOTE. A rule, a short one -- not full width, the way a footnote rule
                      is set -- then the source. `SourceChip` rather than a hand-rolled anchor: this
                      site has exactly one way of drawing "a source you can open", pinned by
                      `__tests__/sourceChipIsTheOnlyOne.test.ts`. */}
                  {source && (
                    <div className="mt-7">
                      <div aria-hidden className="h-px w-24 bg-border" />
                      <div className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span aria-hidden className="flex-none text-caption text-faint">
                          1
                        </span>
                        <SourceChip url={source.url} host={sourceHost(source.url)} variant="link" />
                      </div>
                    </div>
                  )}

                  {/* WHERE THE PAGE IS CUT. The next section starts, and the frame takes it
                      mid-word. It is the pack's own case AGAINST the idea, which is the second-best
                      thing on this sheet: the last impression before the fade is a document
                      arguing with itself. */}
                  {report.adversarial?.killCase && (
                    <div className="mt-9 border-t border-border pt-6">
                      <h3 className="leading-snug sub">
                        The strongest case against this idea
                      </h3>
                      <p className="mt-4 max-w-[62ch] text-body leading-[1.75] text-text">
                        {report.adversarial.killCase}
                      </p>
                    </div>
                  )}
                </div>

                {/* THE FADE. White to transparent over the page's own white, so the page dissolves
                    rather than sitting behind a grey scrim. `pointer-events-none` so it never eats
                    a click on the source link above it. It is SHORTER on mobile: the desktop
                    128px is a fifth of a 38rem page and a quarter of a 29rem one, and every pixel
                    of it is prose the reader cannot finish. The fade has to be long enough to read
                    as a dissolve and no longer. */}
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-surface via-surface/85 to-transparent sm:h-32"
                />
              </article>
            </div>
          </div>
        </div>

        {/* THE PRICE ARGUMENT AND THE ASK, at the FOOT of the argument column so the button's
            baseline meets the bottom edge of the page beside it. `strongestAlternative` is
            engine-written, cited, and it was sitting unused in this JSON several thousand pixels
            from a £49 button. Quoting it is the difference between us asserting the pack is cheap
            and the research stating what the alternative costs. */}
        <div className="min-w-0 lg:col-start-1 lg:row-start-2 lg:self-start">
          {report.premortem?.strongestAlternative && (
            <blockquote className="border-l-2 border-border pl-4">
              <p className="italic lede">{report.premortem.strongestAlternative}</p>
              <footer className="mt-2 text-caption text-subtle">
What people pay for this problem today.
              </footer>
            </blockquote>
          )}

          {/* THE ZERO-RISK STEP NEXT TO THE PAID ONE. The reader meets the product before the
              price, and the button says which page it opens -- "this exact pack" is checkable
              against the sheet they have just read, where "a free sample" would not be. */}
          <div className="mt-6 flex flex-col items-start gap-2">
            <Link href="/sample">
              <Button size="lg">
                Read this exact pack, free
                <Icon name="arrowRight" size={16} />
              </Button>
            </Link>
            <span className="text-caption text-subtle">No payment, no email.</span>
          </div>

          {/* THE REST OF THE FOOTNOTES, and this is the content that fills the column the founder
              read as an empty panel.

              It is the honest thing to put there because it is already on the page: the sheet
              prints footnote 1 under the check's argument and then the frame cuts, so the reader
              can see the check was ruled on sources and cannot see how many or which. Numbering
              continues from the sheet's 1 -- the column is that page's footnote apparatus, run on
              past the crop, which is the same "this document continues" move the crop itself makes.

              It also settles the section's own claim at the point of the ask. The counts line at
              the top says {report.sourceCount} sources across the pack; a reader has no way to
              turn that into a feeling until they see what ONE check's worth looks like, and every
              one of these opens.

              NOT a `SourceChipRow`: that wraps chips inline, which is right where sources are a
              trailing detail under a verdict and wrong here, where the list is the column's
              content and each row carries a caption. The link itself is still `SourceChip`, which
              is the only way this site draws an openable source
              (`__tests__/sourceChipIsTheOnlyOne.test.ts`). */}
          {restSources.length > 0 && (
            <div className="mt-10 border-t border-border pt-6">
              <p className="eyebrow">
                The other {restSources.length} sources behind this one check
              </p>
              <ul className="mt-4 space-y-3">
                {restSources.map((s, i) => {
                  const title = slugTitle(s.url);
                  return (
                    <li key={s.url} className="min-w-0">
                      <div className="flex items-baseline gap-2">
                        {/* The number is `aria-hidden` for the same reason it is on the sheet: a
                            screen reader gets the link, not the ordinal that positions it. */}
                        <span aria-hidden className="flex-none font-mono text-caption text-faint">
                          {i + 2}
                        </span>
                        <SourceChip url={s.url} host={sourceHost(s.url)} variant="link" />
                      </div>
                      {title && (
                        // `truncate`, not a clamp: the caption is supporting detail in a 22rem
                        // column, and a deterministic one-line row is what keeps this block's
                        // height predictable against the sheet beside it.
                        <p className="ml-5 truncate text-caption leading-snug text-faint">
                          {title}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
