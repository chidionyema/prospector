import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Badge, buttonClasses, Glyph, Icon, SourceChip, SourceChipRow, textLinkClass, VerdictChip } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { sourcesLabel } from '@/components/ui/ProofLine';
import { Section, SectionBand } from '@/components/marketing/blocks';
import { WaitlistCallout } from '@/components/waitlist/WaitlistCallout';
import DocRail, { type DocSectionRef } from '@/components/marketing/DocRail';
import { freshnessLabel } from '@/lib/api/client';
import report from '@/data/sample-report.json';

/*
  WHAT THIS PAGE IS, AS OF 2026-08-15.

  It used to publish a WHOLE pack for nothing, under the headline "A whole report. Free, and
  nothing held back." -- three lines above a buy CTA that admitted "a pack adds the build spec,
  the go to market plan, and the operations playbook on top of the evidence record you just
  read" (the old `sample.tsx:174` against `:389`). Both sentences were on screen at once. The
  page whose entire job is to establish that we do not overclaim opened with an overclaim.

  The founder settled it on 2026-08-15: a true excerpt, honestly bounded. Three sections in
  full -- the situation, what you would be selling, and the field with its quoted competitor
  passages -- then a visible stop that NAMES the eleven it does not show. An excerpt that ends
  in a stated place is a stronger argument than a giveaway that has to be walked back at the
  till.

  The content is not written here. `tools/build_sample_fixture.py` renders those three sections
  through the same modules that build the buyer's zip and emits them as typed blocks, so this
  page cannot drift from the product: change the pack and the sample changes with it.
*/

/*
  The inline layer. `tools/build_sample_fixture.py` emits a NODE TREE rather than an HTML string
  -- bare text, and `{tag, children}` for the four inline tags a pack's prose can contain -- so
  nothing on this page is set with `dangerouslySetInnerHTML`. That was a deliberate second pass:
  the first version emitted `html` and drew five `react/no-danger` errors, and five ESLint
  suppressions on the page whose whole argument is "we do not overclaim, go and check us" is the
  wrong trade. The generator refuses to emit a tag outside this union, so the type below and the
  whitelist in that file are the same statement made twice, once at each end.
*/
type Node = string | { tag: 'strong' | 'em' | 'code' | 'a'; href?: string; children: Node[] };

type Inline = { type: 'h2' | 'h3' | 'callout'; nodes: Node[] };
type Para = { type: 'p'; nodes: Node[]; quote?: boolean };
type Rule = { type: 'hr' };
type Bullets = { type: 'ul'; items: Node[][] };
type SourceBlock = {
  type: 'source';
  host: string;
  year: string;
  label: string;
  url: string;
  quote: string;
};
type Block = Inline | Para | Rule | Bullets | SourceBlock;
type ExcerptSection = { id: string; title: string; blocks: Block[] };
type Withheld = { title: string; blurb: string };

/*
  Hoisted to module scope for the same reason the previous version hoisted its checks: `DocRail`
  keys an IntersectionObserver on the `sections` array, and an array rebuilt each render would
  tear the observer down and re-create it every time the rail updated its own active-section
  state. Stable by construction rather than by remembering to memoise.
*/
const EXCERPT = report.excerpt as ExcerptSection[];
const WITHHELD = report.withheld as Withheld[];
const PUSHED_BACK = report.total - report.supported;

/*
  THE DRAWING'S SOURCE LIST (`mockups/sample.html`, `.srclist`): the pack's own "everything we
  read, once" section, a numbered list at the foot of the sheet. Derived from the excerpt rather
  than typed, so it can only ever name pages this page actually quotes. The hero counts this same
  array, so the two cannot disagree; it used to say "six" and this list held four.
*/
const QUOTED_SOURCES = EXCERPT.flatMap((s) => s.blocks).filter(
  (b): b is SourceBlock => b.type === 'source',
);

/*
  THE CHECKS THE EVIDENCE WOULD NOT SETTLE (MASTER-BRIEF section 7: "lead with the check that
  failed").

  This is the most persuasive thing on the site and it is the part a shop would normally bury. A
  research filter that reports six wins is a sales page. One that names, at the top, the two
  questions it could not answer and shows its reasoning for giving up on them is making a claim a
  reader can test. If we were willing to overclaim, this block is the first thing we would delete.

  Derived, never typed: `checks` is the same array the pack ships, so a re-run that settles one of
  these removes it from here with no edit. If a re-run settles both, the block renders nothing.
*/
type SampleCheck = { name: string; key: string; verdict: string; rationale: string };
const UNSETTLED: SampleCheck[] = (report.checks as SampleCheck[]).filter(
  (c) => c.verdict !== 'supported',
);

const SECTIONS: DocSectionRef[] = [
  // First in the rail as well as first on the page. A contents list that starts with the excerpt
  // would put the one honest thing on the page below the fold of its own navigation.
  ...(UNSETTLED.length > 0
    ? [{ id: 'unsettled', label: 'What we could not settle', tone: 'warn' } as DocSectionRef]
    : []),
  ...EXCERPT.map((s): DocSectionRef => ({ id: s.id, label: s.title })),
  ...(QUOTED_SOURCES.length > 0
    ? [{ id: 'sources', label: 'Everything quoted, once' } as DocSectionRef]
    : []),
  { id: 'boundary', label: 'Where the sample stops', note: `${WITHHELD.length} more`, tone: 'kill' },
  { id: 'buy', label: 'Browse the packs' },
];

/** A node tree as React elements. Text is text; a link opens in a new tab, like every other
 *  citation on the site. */
function Rich({ nodes }: { nodes: Node[] }) {
  return (
    <>
      {nodes.map((node, i) => {
        if (typeof node === 'string') return <React.Fragment key={i}>{node}</React.Fragment>;
        const inner = <Rich nodes={node.children} />;
        if (node.tag === 'a') {
          return (
            <a key={i} href={node.href} target="_blank" rel="noreferrer" className={textLinkClass()}>
              {inner}
            </a>
          );
        }
        if (node.tag === 'strong') return <strong key={i} className="font-semibold text-text">{inner}</strong>;
        if (node.tag === 'code') return <code key={i} className="font-mono text-caption">{inner}</code>;
        return <em key={i}>{inner}</em>;
      })}
    </>
  );
}

/** One block of pack prose. */
function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case 'h2':
      // The section title on the page is the <h2>. A `##` inside the section is therefore an
      // <h3>, and a `###` an <h4> -- the pack's own hierarchy shifted down one to sit under this
      // page's, rather than two competing h2 levels in the same column.
      // `text-h3` WAS A DEAD CLASS. `--text-h3` is deleted from the theme (tokens.css:1002), and an
      // unmapped utility in Tailwind v4 emits NOTHING -- so this heading rendered at body size. The
      // mockup's sub-heading step is `h3.sub{clamp(18px,3.2vw,22px);-.02em;655}`
      // (mockups/sample.html:31), which is what `text-h2` carries here: clamp(19px,3.4vw,23px).
      return (
        <h3 className="mt-9 sub">
          <Rich nodes={block.nodes} />
        </h3>
      );
    case 'h3':
      return (
        <h4 className="mt-7 sub">
          <Rich nodes={block.nodes} />
        </h4>
      );
    case 'callout':
      // A lone bolded line in these renderers is always a load-bearing statement -- the payer,
      // the one-liner -- never emphasis inside a sentence. It gets a rule and a bigger measure
      // so the eye stops on it, which is what the bold was doing in the markdown.
      return (
        <p className="mt-5 border-l-2 border-text/20 pl-4 text-body font-medium leading-relaxed text-text">
          <Rich nodes={block.nodes} />
        </p>
      );
    case 'hr':
      return <hr className="mt-8 border-0 border-t border-border" />;
    case 'ul':
      return (
        <ul className="mt-4 list-none space-y-2.5 p-0">
          {block.items.map((item, i) => (
            // 66ch, the drawing's reading measure for pack prose
            // (`.sheet-body p{max-width:66ch}`, mockups/sample.html:284).
            <li key={i} className="flex max-w-[66ch] gap-3 text-meta leading-relaxed text-muted">
              <span className="mt-2 h-1 w-1 flex-none rounded-full bg-text/40" aria-hidden />
              <span><Rich nodes={item} /></span>
            </li>
          ))}
        </ul>
      );
    case 'source':
      return <SourcePassage block={block} />;
    default:
      /* The size, colour, line-height and 66ch measure now come from `.sheet-body p`
         (mockups/sample.html:284), which only works because the utilities that set the same four
         properties are GONE: `mumchimp.css` is imported into `layer(components)` (globals.css:8) and
         Tailwind utilities sit above it, so a paragraph carrying both draws the utility. Only the
         quote's rule and indent stay, because the drawing has no rule for them. */
      return (
        <p className={cx(block.quote && 'border-l-2 border-border pl-4 italic')}>
          <Rich nodes={block.nodes} />
        </p>
      );
  }
}

/**
 * A competitor's own page, quoted, with the link under it.
 *
 * This is the block that has to carry the page's whole argument, so it is the one that gets a
 * card. "The field" section names who is already there; the passage under each name is the
 * evidence that we read them rather than guessed at them. A source with no usable passage still
 * appears -- it is still a source we read -- it just does not get to say anything.
 *
 * `SourceChipRow` and not a local chip. A private copy of this markup is how "the domain leads"
 * became true on /sample and false in the hero; there are five call sites and one component.
 */
function SourcePassage({ block }: { block: SourceBlock }) {
  /* THE EVIDENCE DEVICE, taken from the drawing (`.evidence`, mockups/sample.html:84-87):
     `border-left:2px solid var(--brand);background:var(--brand-tint);padding:15px 17px;
     border-radius:0 12px 12px 0`, the quote at 15.5px/1.55 with a 64ch measure, and the
     attribution under it in mono at 12px. It was a plain bordered white card, which is the same
     object as every other card on the page -- the whole point of this block is that a quoted
     passage is a different KIND of thing from our own prose, and the teal edge is what says so.
     `rounded-r-md` is the bounded vocabulary's right-corner radius; the mockup's 0/12/12/0 has no
     utility here and 8px is the nearest legal corner. */
  /* Now the class itself, not a copy of it in utilities. Everything the comment above describes
     is in `.evidence` and `.evidence p` and `.evidence .src`; the utilities that restated it are
     removed, because layered above `mumchimp.css` they were the reason the class drew nothing. */
  return (
    <figure className="evidence">
      {block.quote ? (
        <blockquote>&ldquo;{block.quote}&rdquo;</blockquote>
      ) : (
        <p>Read, but nothing in it was quotable as a clean passage.</p>
      )}
      <figcaption className="src flex flex-wrap items-center gap-x-3 gap-y-2">
        <SourceChipRow sources={[{ url: block.url, host: block.host, label: block.label }]} />
        {block.year && <span>{block.year}</span>}
      </figcaption>
    </figure>
  );
}

export default function SamplePage() {
  /* `6xl` to match `LegalDoc.tsx:108`, the site's other document-with-a-rail page, so the trail
     starts on the same left edge as the prose under it rather than the 3xl default.
     This page reached main WITHOUT a trail: the rule that every visual route offers a way back
     landed on the branch (`backNavigation.test.ts`) at the same time as this page was rewritten
     on main, and a textual merge keeps both without noticing that the new page breaks the new
     rule. The test is what caught it. */
  return (
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Packs' }, { href: '#', label: 'Sample' }]}
      breadcrumbsWidth="6xl"
    >
      {/* Its own description, not the site default, and no longer the word "unredacted". The
          previous copy promised "a complete Mumchimp report free, unredacted" -- a search snippet
          that the page below it could not honour once the boundary went in. A snippet that
          oversells is worse than a generic one: it converts a click into a disappointment. */}
      <Seo
        title="Read the opening of a real pack, free"
        description="The first three sections of a published Mumchimp pack, in full and unedited: the situation, what you would be selling, and the competitors already there. Every claim is quoted from its own page, with the link. It stops where the working sections begin."
      />

      {/* Hero. Left-aligned, and on the SAME `7xl` band and rail grid as the document below, so
          the page has one left edge. It was `6xl` with no grid once: the headline started at the
          6xl margin while every line of the report started at 7xl plus the 14rem rail, which is
          the two-left-margins defect `storefrontDesignContract` exists to catch. */}
      {/* `.pagetop{padding:14px 0 8px}` (mockups/sample.html:66). The page top sits directly under
          the breadcrumb in the drawing, not a band's worth of air below it: it was
          `pt-14 pb-8 md:pt-20 md:pb-10`, so the h1 started 56-80px down where the drawing starts it
          14px down. The grid is the reader's, so the headline shares a left edge with the prose. */}
      <SectionBand bg="white" width="7xl" className="pt-3.5 pb-2">
        <div className="lg:grid lg:grid-cols-[230px_minmax(0,1fr)] lg:gap-[30px]">
          <div aria-hidden />
          <div className="min-w-0">
            {/* The drawing's top strip: a verdict pill, then the terms of the offer in mono, on one
                line above the headline (`.metastrip` with `<span class="v s">Free to read</span>`,
                mockups/sample.html:330). The section count stays because it is a fact off
                sample-report.json and the drawing's page is a different sample from ours. */}
            {/* NOT MONO, though `.metastrip` is (`mockups/sample.html`). The line is mostly words,
                and `monoIsTheDataVoice.test.ts` caps the site's mono budget and holds the face for
                figures. The drawing's position, size and colour survive; the face does not. */}
            <div className="pagetop">
            <p className="metastrip num mb-3.5">
              <Badge tone="success">Free to read</Badge>
              <span>
                no payment · no email · no account · {report.sectionsShown} of{' '}
                {report.sectionsTotal} sections
              </span>
            </p>
            {/* States what the thing IS and where it ends, in one line. The reader decides what
                it proves; the headline does not tell them to be suspicious of us first, and it
                does not promise a whole pack the page then withholds. */}
            <h1 className="max-w-[24ch]">
              The opening of a real pack, in full.
            </h1>
            <p className="lede big mt-6">
              Not a mock-up and not a summary. These are the first three sections of a pack that
              is available right now, exactly as they were published: the situation somebody is
              already dealing with, what you would actually be selling, and who is already in the
              field, quoted from their own pages, with every link open.
            </p>
            </div>
            <div className="metastrip num mt-7">
              {/* THE UNSETTLED COUNT COMES FIRST. It used to sit second, behind "N checks
                  cleared", which is the ordering a shop reaches for and the wrong one here. The
                  cleared count is what every seller claims; the count we could not settle is the
                  one that can be checked against the reasoning below, and it is the reason to
                  believe the other number. Section 7 asks the page to lead with it. */}
              {PUSHED_BACK > 0 && (
                <span className="inline-flex items-center gap-2 text-warning-strong">
                  <Glyph name="pushed-back" className="text-warning" />
                  {PUSHED_BACK === 1 ? '1 check the evidence would not settle' : `${PUSHED_BACK} checks the evidence would not settle`}
                </span>
              )}
              <span className="inline-flex items-center gap-2">
                <Glyph name="survived" className="text-success" />
                {report.supported} checks cleared
              </span>
              {/* The one anchor on this strip, and it lands somewhere that proves the number
                  rather than restating it: the third section quotes five of these pages at
                  length. The old strip linked "objections we could not dismiss" to `#pushback`,
                  an id on a checks list that this page no longer renders -- a hero link to
                  nowhere is the classic casualty of a page restructure, so this one points at a
                  section the rail also lists. */}
              <a href={`#${EXCERPT[2]?.id ?? 'boundary'}`} className={textLinkClass('inline-flex items-center gap-2')}>
                <Glyph name="source" className="text-success" />
                {/* Derived, never typed (2026-08-30). The literal here read "six" while the
                    sheet 100 lines below counted the same list and rendered "4 of 29 read": one
                    load, one page, two numbers for one fact. This is the page the founder's
                    2026-08-15 ruling says exists to prove the site does not overclaim, so it is
                    the one page a wrong count costs the most. Both now count the same array. */}
                {`${sourcesLabel(report.sourceCount)} cited, ${QUOTED_SOURCES.length} of them quoted below`}
              </a>
              {freshnessLabel(report.verifiedAt) && (
                <span className="inline-flex items-center gap-2">
                  {freshnessLabel(report.verifiedAt)}
                </span>
              )}
            </div>
          </div>
        </div>
      </SectionBand>

      <Section bg="bg" width="7xl" className="!pt-6 !pb-24">
        {/* THE DRAWING'S READER (`mockups/sample.html`, `.reader`): a 230px contents card and the
            sheet beside it, 30px apart, both aligned to the top. The utilities held the same two
            columns at different numbers, one layer above the class, which made the class inert. */}
        <div className="reader">
          <DocRail sections={SECTIONS} eyebrow="The excerpt · contents" />
          <div className="min-w-0">
            {/* What the reader is about to read, named before they read it. The pack itself
                opens on the situation rather than on a title page, so this line is the only
                framing the page adds -- the sections below are the document's own words. */}
            {UNSETTLED.length > 0 && (
              <section id="unsettled" className="mb-10 scroll-mt-24 rounded-md border border-warning bg-warning-bg p-8 md:p-9">
                {/* `sub` -- `mumchimp.css:15` `h3.sub{clamp(19px,3.4vw,23px);-.02em;655}`, ported
                    to this element at `globals.css`. One step under the `sec` every other
                    heading on this page wears, because the box is an aside to the report and
                    must not read louder than the report's own title. It carried the dead
                    `text-h3` until 2026-08-30 and rendered at 16px, the body size. */}
                <h2 className="sub text-warning-strong">
                  {UNSETTLED.length === 1
                    ? 'One question the evidence would not settle'
                    : `${UNSETTLED.length} questions the evidence would not settle`}
                </h2>
                {/* AMBER, NOT RED. Section 2 gives red one meaning on this site: the idea died.
                    Nothing died here. These are checks the retrieval could not decide either way,
                    which is a different state and gets a different colour. */}
                <p className="mt-3 max-w-[68ch] text-meta leading-relaxed text-warning-strong">
                  This pack is available now, so it cleared every check that can kill an idea. These
                  are the ones the sources would not answer. They are in the pack you would buy,
                  worded exactly like this.
                </p>
                <dl className="mt-6 space-y-5">
                  {UNSETTLED.map((check) => (
                    <div key={check.key}>
                      {/* `.v.p`, the drawing's amber verdict tag (`mockups/sample.html`, where the
                          same check reads `<span class="v p">Unverifiable</span>`). Through
                          `VerdictChip` so the glyph comes with it and the colour is never the sole
                          carrier. `.v.s` does not appear on this page: the drawing spends it on
                          "Free to read", which is a price, not a verdict. */}
                      <dt className="flex flex-wrap items-baseline gap-x-3 gap-y-2 text-body font-semibold text-text">
                        <span>{check.name}</span>
                        <VerdictChip kind="pushed-back" label="Unverifiable" />
                      </dt>
                      <dd className="mt-1 ml-0 max-w-[68ch] text-meta leading-relaxed text-muted">
                        {check.rationale}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            <div className="rounded-card border border-border bg-surface p-8 md:p-9">
              <span className="text-caption font-medium text-muted">The pack</span>
              <h2 className="sec">{report.title}</h2>
              <p className="mt-4 lede">
                {report.oneLiner}
              </p>
            </div>

            {/* THE SHEET (`mockups/sample.html`, `.sheet` / `.sheet-top` / `.sheet-body`). Each
                section of the pack is a bordered sheet with a mono strip across the top naming the
                document and its place in the run, then the prose inset by the drawing's 20px pad.
                The strip is what makes the excerpt read as pages OUT OF something: the section
                number and "of 14" are the fact the boundary block below depends on, and putting
                them in the sheet's own header says it once per section instead of once per page. */}
            {EXCERPT.map((section, i) => (
              <section key={section.id} id={section.id} className="mt-14 scroll-mt-24">
                <div className="sheet">
                  <div className="sheet-top">
                    <span>
                      Section {String(i + 1).padStart(2, '0')} &middot; {section.title}
                    </span>
                    <span className="num">
                      {i + 1} of {report.sectionsTotal}
                    </span>
                  </div>
                  <div className="sheet-body">
                    <h2 className="sec">{section.title}</h2>
                    <div className="mt-5">
                      {section.blocks.map((block, j) => (
                        <BlockView key={j} block={block} />
                      ))}
                    </div>
                  </div>
                </div>
              </section>
            ))}

            {QUOTED_SOURCES.length > 0 && (
              <section id="sources" className="mt-14 scroll-mt-24">
                <div className="sheet">
                  <div className="sheet-top">
                    <span>Everything quoted above, once</span>
                    <span className="num">
                      {QUOTED_SOURCES.length} of {report.sourceCount} read
                    </span>
                  </div>
                  <div className="sheet-body">
                    {/* `.srclist`: the numbered list the drawing puts at the foot of the sheet.
                        Every entry is a page quoted above, so the list cannot claim a source the
                        page does not show. The other {report.sourceCount - QUOTED_SOURCES.length}
                        are cited inside the sections the sample does not include. */}
                    <ol className="srclist">
                      {QUOTED_SOURCES.map((source, i) => (
                        <li key={`${source.url}-${i}`}>
                          <span className="i num">{i + 1}</span>
                          {/* `SourceChip`, not a hand-rolled anchor. The drawing's srclist entry is
                              a bare link on the hostname, which is exactly the `link` variant, and
                              `sourceChipIsTheOnlyOne.test.ts` catches the copy: this list was a
                              plain `<a target="_blank">{source.host}</a>` for one commit and the
                              test failed it, which is the whole reason that test exists. */}
                          <span>
                            <SourceChip url={source.url} host={source.host} variant="link" />{' '}
                            &middot; {source.label}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </div>
                </div>
              </section>
            )}

            {/* THE BOUNDARY. The whole point of the restructure: a visible stop that names what
                is behind it, rather than a giveaway that gets walked back at the buy CTA. */}
            <section
              id="boundary"
              className="mt-16 scroll-mt-24 rounded-md border border-warning/30 bg-warning/5 p-7 md:p-9"
            >
              <div className="flex items-center gap-2">
                <Glyph name="pushed-back" className="text-warning" />
                <span className="text-caption font-medium text-warning">
                  This is where the sample stops
                </span>
              </div>
              <h2 className="mt-3 max-w-[28ch] sec">
                You have read the reporting. The rest is the working half.
              </h2>
              <p className="mt-4 lede">
                Three sections of {report.sectionsTotal}. What you have just read is what we found
                out; the {WITHHELD.length} below are what you would do about it: what it costs,
                what would sink it, what to build first, and how to know inside a month whether you
                were wrong. Every one of them is written from the same checked claims, on the same
                sources, and they are the reason a pack costs money.
              </p>
              <dl className="mt-7 grid grid-cols-1 gap-x-10 gap-y-5 sm:grid-cols-2">
                {WITHHELD.map((w) => (
                  <div key={w.title}>
                    <dt className="text-meta font-semibold text-text">{w.title}</dt>
                    <dd className="mt-1 text-meta leading-relaxed text-muted">{w.blurb}</dd>
                  </div>
                ))}
              </dl>
              {/* The excerpt above points at two sections by name -- the checks record and the
                  fortnight plan -- because the document was written to be read whole. Leaving
                  those references intact and explaining them is more honest than editing the
                  excerpt to hide that it is one. */}
              <p className="mt-7 border-t border-warning/30 pt-5 lede">
                The excerpt refers to two of these by name. That is the pack talking to its own
                reader, not a tease, and we did not rewrite it to pretend the sample is the whole
                document.
              </p>
            </section>

            {/* THE DRAWING'S CLOSING (`mockups/sample.html`, `.closing`): a 2px ink rule, the
                sentence, then a `.ctarow` of two ways out. It was a centred card, which reads as
                one more panel in a stack of panels rather than as the end of the document, and it
                offered only the shelf. */}
            <div id="buy" className="closing scroll-mt-24">
              <h2 className="sec" style={{ maxWidth: '26ch' }}>
                Now read one that survived all of it.
              </h2>
              <p>
                You can now go and read the catalogue with these answers in mind. One payment, yours to
                keep, no account to make.
              </p>
              <div className="ctarow">
                <Link href="/#catalog" className="btn">
                  Browse the packs
                  <Icon name="arrowRight" size={15} />
                </Link>
                <Link href="/how-it-works" className="btn ghost">
                  See how the filter works
                </Link>
              </div>
            </div>

            {/* Second position, under the buy CTA: a reader who wants a pack should buy one, and
                the address is only the fallback when nothing on the shelf fits them yet. */}
            <WaitlistCallout />
          </div>
        </div>
      </Section>
    </MarketingLayout>
  );
}
