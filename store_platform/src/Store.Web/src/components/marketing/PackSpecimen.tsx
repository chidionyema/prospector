import Link from 'next/link';

import report from '@/data/sample-report.json';
import { PACK_DOCUMENTS } from '@/components/marketing/PackContents';
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
 * non-`supported` check the data contains, and every line of copy that mentions a failure is
 * gated on `SHOWS_A_FAILURE`. Re-generate the sample with eight clean checks and this section
 * degrades to an honest specimen with no flaw claim, rather than to a lie.
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
 * The failed check, found rather than named. `?? at()` keeps the component renderable against a
 * sample where everything passed; `SHOWS_A_FAILURE` is what every claim about a failure is gated
 * on, so that case degrades the COPY instead of leaving it false.
 */
const FAILED_INDEX = CHECKS.findIndex((check) => check.verdict !== 'supported');
const FAILED = FAILED_INDEX >= 0 ? CHECKS[FAILED_INDEX] : CHECKS[CHECKS.length - 1];
const SHOWS_A_FAILURE = FAILED?.verdict !== 'supported';
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

/** The section of the pack this page belongs to, read from the manifest so it cannot drift. */
const SECTION_TITLE =
  PACK_DOCUMENTS.find((doc) => doc.section === 'Evidence_and_Constraints.md')?.title ??
  'Evidence and Constraints';

export function PackSpecimen({ className }: { className?: string }) {
  const source = FAILED?.sources?.[0];

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
      <div className="grid gap-10 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:gap-14">
        <div className="lg:col-start-1 lg:row-start-1">
          {/* The eyebrow is SANS. The wide-tracked all-caps mono eyebrow is the exact pattern
              `__tests__/monoIsTheDataVoice.test.ts` was written to stop spreading: mono is the
              evidence voice -- amounts, IDs, hostnames, scores -- and "a page from the free
              sample" is human language. The mono in this component is spent on the three things a
              reader could transcribe: the check counter, the confidence figure and the caption
              rail's counts. (That test reads raw source lines, so naming those utilities together
              in a comment is itself an offence -- which is why this spells them out in words.) */}
          <p className="text-caption font-medium text-subtle">A page from the free sample</p>

          {/* The headline states the SCALE and then immediately stops asserting it, which is the
              whole argument of the section in one move: the number answers "is this a two-page
              Google Doc?", and the page beside it answers "prove it". */}
          <h2 className="mt-2 text-h2 font-semibold text-text">
            {PACK_DOCUMENTS.length} documents. Here is one page of one of them.
          </h2>
          <p className="mt-4 max-w-[46ch] text-body text-muted">
            {SHOWS_A_FAILURE ? (
              <>
                Unretouched, from the pack you can read for nothing. We picked the page with the
                failed check on it, because a flaw is the one thing nobody puts in their own product
                by accident.
              </>
            ) : (
              <>
                Unretouched, from the pack you can read for nothing. Every claim on it carries the
                source it came from, and those sources open.
              </>
            )}
          </p>

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

        <div className="lg:col-start-2 lg:row-start-1 lg:row-span-2">
          {/* THE PLINTH. `--surface3` behind white paper is what makes the paper read as paper; on
              the page's own white it would read as a bordered div. It HUGS the sheet -- the grey is
              a margin, not a stage. The padding is asymmetric because the stack is offset down and
              right and must not touch the plinth's edge. */}
          <div className="rounded-md border border-border bg-surface3 p-4 sm:p-8">
            <div className="relative pb-3 pr-3">
              {/* THE SHEETS UNDERNEATH: two, not three -- at three the offsets start reading as a
                  deliberate graphic rather than as a stack that happens to be there. They are
                  `aria-hidden` and carry no text: a screen reader gets the page once. */}
              <div
                aria-hidden
                className="absolute left-3 top-3 h-full w-full rounded-sm border border-border bg-surface"
              />
              <div
                aria-hidden
                className="absolute left-1.5 top-1.5 h-full w-full rounded-sm border border-border bg-surface"
              />

              {/* THE PAGE. `overflow-hidden` is the crop; nothing inside it is sticky (that
                  combination silently kills every descendant sticky -- memory:
                  `overflow-hidden-kills-every-descendant-sticky`). The heights are the mobile floor
                  described in the docblock, measured to keep four elements above the fade at
                  360px. */}
              <article className="relative max-h-[29rem] overflow-hidden rounded-sm border border-border bg-surface sm:max-h-[38rem]">
                {/* DOCUMENT MARGINS, not card padding. Wider at the sides than a card would be,
                    and the type inside runs to a ~62ch measure rather than to the container. */}
                <div className="px-6 pb-10 pt-7 sm:px-12 sm:pb-14 sm:pt-11">
                  {/* THE RUNNING HEAD. Sans, because both halves are titles -- human language. The
                      hairline under it is the single most "this is a typeset page" signal
                      available for one border-width of cost. */}
                  <div className="flex items-baseline justify-between gap-4 border-b border-border pb-3">
                    <span className="min-w-0 truncate text-caption font-medium text-text">
                      {report.title}
                    </span>
                    <span className="flex-none text-caption text-subtle">{SECTION_TITLE}</span>
                  </div>

                  {/* THE MID-SENTENCE OPENING. Real text: the closing clause of the check printed
                      immediately before this one, quoted with a leading ellipsis. This is the line
                      that does the "there are pages before this one" work, and it does it without
                      claiming a page count we cannot substantiate. */}
                  <p className="mt-6 max-w-[62ch] text-body leading-[1.75] text-muted">
                    …{sentenceTail(PRECEDING?.rationale ?? '')}
                  </p>

                  {/* THE SECTION HEADING, numbered the way a document numbers itself. The counter
                      is mono -- it is a figure a reader could compare against the eight marks in
                      the hero and against the pack's own QA report. */}
                  <div className="mt-8 flex flex-wrap items-baseline gap-x-3 gap-y-2 border-t border-border pt-6">
                    <span className="flex-none font-mono text-caption text-subtle">
                      {PAGE_NUMBER} of {CHECKS.length}
                    </span>
                    <h3 className="min-w-0 flex-1 text-h3 font-semibold leading-snug text-text">
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
                    <span className="font-mono text-caption text-subtle">
                      confidence {FAILED?.confidence}
                    </span>
                  </p>

                  {/* THE BODY, at document scale: `text-body` with 1.75 leading and a 62ch measure.
                      This is the paragraph that has to survive being read closely, which is why it
                      is the report's own words and not a description of them. */}
                  <p className="mt-5 max-w-[62ch] text-body leading-[1.75] text-text">
                    {FAILED?.rationale}
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
                      <h3 className="text-h3 font-semibold leading-snug text-text">
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
        <div className="lg:col-start-1 lg:row-start-2 lg:self-end">
          {report.premortem?.strongestAlternative && (
            <blockquote className="border-l-2 border-border pl-4">
              <p className="text-body italic text-muted">{report.premortem.strongestAlternative}</p>
              <footer className="mt-2 text-caption text-subtle">
                The alternative, as this pack’s own research put it.
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
        </div>
      </div>
    </div>
  );
}
