import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses, Glyph, Icon, SourceChipRow, textLinkClass } from '@/components/ui';
import { cx } from '@/components/ui/cx';
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

const SECTIONS: DocSectionRef[] = [
  ...EXCERPT.map((s): DocSectionRef => ({ id: s.id, label: s.title })),
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
      return (
        <h3 className="mt-9 text-h3 font-semibold text-text">
          <Rich nodes={block.nodes} />
        </h3>
      );
    case 'h3':
      return (
        <h4 className="mt-7 text-body font-semibold text-text">
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
            <li key={i} className="flex max-w-[68ch] gap-3 text-meta leading-relaxed text-muted">
              <span className="mt-2 h-1 w-1 flex-none rounded-full bg-text/40" aria-hidden />
              <span><Rich nodes={item} /></span>
            </li>
          ))}
        </ul>
      );
    case 'source':
      return <SourcePassage block={block} />;
    default:
      return (
        <p
          className={cx(
            'mt-4 max-w-[68ch] leading-relaxed',
            block.quote ? 'border-l-2 border-border pl-4 text-meta italic text-muted' : 'text-body text-muted',
          )}
        >
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
  return (
    <figure className="mt-5 rounded-md border border-border bg-surface p-5 md:p-6">
      {block.quote ? (
        <blockquote className="max-w-[64ch] text-meta leading-relaxed text-text">
          &ldquo;{block.quote}&rdquo;
        </blockquote>
      ) : (
        <p className="text-meta leading-relaxed text-muted">
          Read, but nothing in it was quotable as a clean passage.
        </p>
      )}
      <figcaption className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border pt-4">
        <SourceChipRow sources={[{ url: block.url, host: block.host, label: block.label }]} />
        {block.year && (
          <span className="font-mono text-caption text-muted">{block.year}</span>
        )}
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
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'Sample' }]}
      breadcrumbsWidth="6xl"
    >
      {/* Its own description, not the site default, and no longer the word "unredacted". The
          previous copy promised "a complete Mumchimp report free, unredacted" -- a search snippet
          that the page below it could not honour once the boundary went in. A snippet that
          oversells is worse than a generic one: it converts a click into a disappointment. */}
      <Seo
        title="Read the opening of a real pack, free"
        description="The first three sections of a published Mumchimp pack, in full and unedited: the situation, what you would be selling, and the competitors already there, quoted from their own pages with every link. It stops where the working sections begin."
      />

      {/* Hero. Left-aligned, and on the SAME `7xl` band and rail grid as the document below, so
          the page has one left edge. It was `6xl` with no grid once: the headline started at the
          6xl margin while every line of the report started at 7xl plus the 14rem rail, which is
          the two-left-margins defect `storefrontDesignContract` exists to catch. */}
      <SectionBand bg="white" width="7xl" className="pt-14 pb-8 md:pt-20 md:pb-10">
        <div className="lg:grid lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-14">
          <div aria-hidden />
          <div className="min-w-0">
            <p className="mb-4 text-caption font-medium text-muted">
              The free sample · {report.sectionsShown} of {report.sectionsTotal} sections
            </p>
            {/* States what the thing IS and where it ends, in one line. The reader decides what
                it proves; the headline does not tell them to be suspicious of us first, and it
                does not promise a whole pack the page then withholds. */}
            <h1 className="max-w-[24ch] text-balance text-h1 font-semibold text-text">
              The opening of a real pack, in full.
            </h1>
            <p className="mt-6 max-w-[64ch] text-body leading-relaxed text-muted">
              Not a mock-up and not a summary. These are the first three sections of a pack that
              is on the shelf right now, exactly as they were published: the situation somebody is
              already dealing with, what you would actually be selling, and who is already in the
              field, quoted from their own pages, with every link open.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-2 text-meta font-semibold text-muted">
              <span className="inline-flex items-center gap-2">
                <Glyph name="survived" className="text-success" />
                {report.supported} checks cleared
              </span>
              {PUSHED_BACK > 0 && (
                <span className="inline-flex items-center gap-2">
                  <Glyph name="pushed-back" className="text-warning" />
                  {PUSHED_BACK === 1 ? '1 the evidence would not settle' : `${PUSHED_BACK} the evidence would not settle`}
                </span>
              )}
              {/* The one anchor on this strip, and it lands somewhere that proves the number
                  rather than restating it: the third section quotes five of these pages at
                  length. The old strip linked "objections we could not dismiss" to `#pushback`,
                  an id on a checks list that this page no longer renders -- a hero link to
                  nowhere is the classic casualty of a page restructure, so this one points at a
                  section the rail also lists. */}
              <a href={`#${EXCERPT[2]?.id ?? 'boundary'}`} className={textLinkClass('inline-flex items-center gap-2')}>
                <Glyph name="source" className="text-success" />
                {report.sourceCount} cited sources, six of them quoted below
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
        <div className="lg:grid lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-14">
          <DocRail sections={SECTIONS} eyebrow="The excerpt · contents" />
          <div className="min-w-0">
            {/* What the reader is about to read, named before they read it. The pack itself
                opens on the situation rather than on a title page, so this line is the only
                framing the page adds -- the sections below are the document's own words. */}
            <div className="rounded-md border border-border bg-surface p-8 md:p-9">
              <span className="text-caption font-medium text-muted">The pack</span>
              <h2 className="mt-2 text-h2 font-semibold text-text md:text-h1">{report.title}</h2>
              <p className="mt-4 max-w-[68ch] text-body leading-relaxed text-muted">
                {report.oneLiner}
              </p>
            </div>

            {EXCERPT.map((section, i) => (
              <section key={section.id} id={section.id} className="mt-14 scroll-mt-24">
                <div className="flex items-baseline gap-3">
                  {/* The numbering is not decoration: these are sections one, two and three of
                      a fourteen-section document, and the count is the fact the boundary below
                      depends on. A reader who has seen "01 / 02 / 03" understands what "11 more"
                      means without being told twice. */}
                  <span className="font-mono text-caption font-medium text-muted">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <h2 className="text-h2 font-semibold text-text">{section.title}</h2>
                </div>
                <div className="mt-5">
                  {section.blocks.map((block, j) => (
                    <BlockView key={j} block={block} />
                  ))}
                </div>
              </section>
            ))}

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
              <h2 className="mt-3 max-w-[28ch] text-balance text-h2 font-semibold text-text">
                You have read the reporting. The rest is the working half.
              </h2>
              <p className="mt-4 max-w-[68ch] text-body leading-relaxed text-muted">
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
              <p className="mt-7 max-w-[68ch] border-t border-warning/30 pt-5 text-meta leading-relaxed text-muted">
                The excerpt refers to two of these by name. That is the pack talking to its own
                reader, not a tease, and we did not rewrite it to pretend the sample is the whole
                document.
              </p>
            </section>

            <div
              id="buy"
              className="mt-12 scroll-mt-24 rounded-md border border-border bg-surface p-8 text-center md:p-10"
            >
              <h2 className="mx-auto max-w-[26ch] text-balance text-h2 font-semibold text-text md:text-h1">
                Every pack on the shelf opens like this.
              </h2>
              <p className="mx-auto mt-3 max-w-[56ch] text-body leading-relaxed text-muted">
                You can now go and read the shelf with these answers in mind. One payment, yours to
                keep, no account to make.
              </p>
              <Link href="/#catalog" className={buttonClasses({ size: 'lg', className: 'mt-6' })}>
                Browse the packs
                <Icon name="arrowRight" size={15} />
              </Link>
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
