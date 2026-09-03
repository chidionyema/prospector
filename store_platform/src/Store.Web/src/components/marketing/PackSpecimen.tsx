import Link from 'next/link';

import report from '@/data/sample-report.json';
import { PACK_DOCUMENTS } from '@/components/marketing/PackContents';
import { plainEnglish } from '@/lib/plainEnglish';
import { SourceChip, sourceHost } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { pickPassedSampleCheck } from '@/lib/sourceGate';

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
const SAMPLE = pickPassedSampleCheck(CHECKS, 'UK') ?? CHECKS.find((c) => c.verdict === 'supported') ?? CHECKS[0];
const SAMPLE_INDEX = Math.max(0, CHECKS.findIndex((c) => c === SAMPLE || (c.key && SAMPLE && c.key === SAMPLE.key)));
const PAGE_NUMBER = SAMPLE_INDEX + 1;
const FAILED = SAMPLE;

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
  /** Footnote 1 is printed on the sheet; 2..n are the list under it. */
  const restSources = (FAILED?.sources ?? []).slice(1);

  /*
   * THE DRAWING'S SECTION (`mockups/index.html:445`, section 10 "SAMPLE, PROMOTED").
   *
   * What was here before: a two-column composition, argument on the left, and on the right a
   * white sheet on a grey plinth with two offset rectangles behind it, cropped at 36rem and
   * dissolved into a gradient. It was drawn to read as a piece of paper.
   *
   * The drawing does none of that. It is one full-width column: the eyebrow, a headline, a mono
   * counts line, then a plain bordered document with a running head, a body and a foot, then the
   * remaining sources as a numbered list. No plinth, no stack, no crop, no fade.
   *
   * Founder, 2026-08-18: "A page from the free sample looks not like nockup". The drawing wins.
   * Nothing that was on the page is dropped by the change: the mid-sentence opening, the failed
   * check with its verdict flag, the kill case, the strongest alternative, footnote 1 and the
   * remaining sources are all still here, in the drawing's order.
   *
   * WHY THE PAGE IS STILL THE FAILED CHECK. Eight green ticks read as marketing; one refutation
   * reads as a document. `FAILED` is the first non-`supported` check the data contains, and no
   * copy anywhere states which page was chosen or why. Re-generate the sample with clean checks
   * and this simply prints that check's own verdict word instead.
   */
  return (
    <section className={cx('sample', className)}>
      <span className="eyebrow">A page from the free sample</span>
      <h2 className="sec mt-3 max-w-[24ch]">
        {FAILED_INDEX >= 0
          ? 'This is what a passed check looks like.'
          : 'This is what one check looks like.'}
      </h2>
      <p className="meta num">
        {CHECKS.length} checks · {report.sourceCount} sources · 5,000+ words · free, no email
      </p>

      <div className="doc">
        <div className="doc-top">
          {/* The section name is read from `PACK_DOCUMENTS`, so the page cannot claim to belong
              to a document the manifest further down the page does not list. */}
          <span className="nm">
            {report.title}, {SECTION_TITLE}
          </span>
          <span className="of num">
            Check {PAGE_NUMBER} of {CHECKS.length}
          </span>
        </div>

        <div className="doc-body">
          {/* THE MID-SENTENCE OPENING. Real text: the closing clause of the check printed
              immediately before this one, quoted with a leading ellipsis. It does the "there are
              pages before this one" work without claiming a page count we cannot substantiate. */}
          <p className="elide">…{sentenceTail(plainEnglish(PRECEDING?.rationale ?? ''))}</p>

          <div className="check-h">
            <h3>{FAILED?.name}</h3>
            {/* The caps are in the VALUE, not in a class. `__tests__/weightAndCasePolicy.test.ts`
                bans `text-transform`: a CSS-uppercased string is copied, read aloud and indexed in
                its original case, so the markup and the screen would disagree. */}
            <span className="flag">{(FAILED?.verdict ?? '').toUpperCase()}</span>
          </div>
          <p>{FAILED?.rationale}</p>
          {source && (
            <p className="cite num">
              1 <SourceChip url={source.url} host={sourceHost(source.url)} variant="link" />
            </p>
          )}

          {report.adversarial?.killCase && (
            <>
              <h4>The strongest case against this idea</h4>
              <p>{report.adversarial.killCase}</p>
            </>
          )}

          {/* `strongestAlternative` is engine-written and cited. Quoting it is the difference
              between us asserting the pack is cheap and the research stating what the alternative
              costs. */}
          {report.premortem?.strongestAlternative && (
            <div className="quote">
              <span>{report.premortem.strongestAlternative}</span>
              What people pay for this problem today.
            </div>
          )}
        </div>

        <div className="doc-foot">
          <Link className="btn sm" href="/sample">
            Read this exact pack, free
          </Link>
          <span className="fine">No payment, no email.</span>
        </div>
      </div>

      {restSources.length > 0 && (
        /* The sheet prints footnote 1 under the check's argument. This is the rest of that page's
           footnote apparatus, numbered on from 1, so a reader can see the check was ruled on more
           than one source and open every one. The link is `SourceChip`, which is the only way this
           site draws an openable source (`__tests__/sourceChipIsTheOnlyOne.test.ts`). */
        <div className="othersrc">
          <h3>The other {restSources.length} sources behind this one check</h3>
          <ol>
            {restSources.map((s, i) => {
              const title = slugTitle(s.url);
              return (
                <li key={s.url}>
                  <span className="i">{i + 2}</span>
                  <span className="min-w-0 break-words">
                    <SourceChip url={s.url} host={sourceHost(s.url)} variant="link" />
                    {title ? `, ${title}` : ''}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </section>
  );
}
