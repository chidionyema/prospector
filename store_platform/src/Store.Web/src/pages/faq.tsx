import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, SectionBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { buttonClasses, chipClasses, Icon, SearchInput, textLinkClass } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { LEGAL } from '@/lib/config';
import { FAQS, isLink, plainAnswer, type FaqItem } from '@/lib/faqContent';
import { breadcrumbNode, faqPageNode, graph } from '@/lib/seo/schema';
import { SITE_COPY } from '@/lib/siteCopy';

/** One answer's segments as prose. */
function Answer({ item }: { item: FaqItem }) {
  return (
    <>
      {item.answer.map((segment, i) => {
        if (!isLink(segment)) return <React.Fragment key={i}>{segment}</React.Fragment>;
        const className = textLinkClass('font-medium');
        return segment.href.startsWith('/') ? (
          <Link key={i} href={segment.href} className={className}>
            {segment.text}
          </Link>
        ) : (
          <a key={i} href={segment.href} className={className}>
            {segment.text}
          </a>
        );
      })}
    </>
  );
}

const CATEGORIES = [
  { key: 'packs', label: 'About the packs' },
  { key: 'payment', label: 'Payment & access' },
  { key: 'process', label: 'Vetting process' },
] as const;

function AccordionItem({
  item,
  defaultOpen,
}: {
  item: FaqItem;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);

  return (
    /* The row draws only its own bottom rule; the LIST draws the box. Both used to: every item
       carried `rounded-md border border-border` inside a parent with `divide-y divide-border`, so between two
       rows sat item N's bottom hairline and item N+1's top hairline with no gap -- measured at
       1px + 1px against 1px at the ends of the list (Playwright getComputedStyle, 2026-08-06). A
       divider twice the weight of the one below it reads as a section break that isn't there. */
    /* mockups/faq.html:184 `.faq details{border-bottom:1px solid var(--line);padding:16px 0}`.
       The rows are set as a plain run of rules on the page, NOT as a bordered card: the mockup's
       list has no box and no side padding, so the questions start on the band's own left edge
       like every other line of the page. The 16px is on the button (`py-4`) so the whole
       summary row is the click target. */
    <div className="transition-colors border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start justify-between gap-4 py-4 text-left"
      >
        {/* mockups/faq.html:185 `.faq summary{font-size:16.5px;font-weight:620;letter-spacing:-.014em}` */}
        <h2 className="tracking-[-0.014em] leading-snug sub">{item.question}</h2>
        {/* mockups/faq.html:187-188: the marker is a typographic + that becomes a minus when open,
            20px, weight 400, in --ink-3. It was a rotating arrow glyph, which is a different
            control. U+2212 MINUS SIGN, not an en dash: `__tests__/dashFree.test.ts` bans both
            dashes in source, and a minus is the correct character here anyway. */}
        <span
          aria-hidden="true"
          className={cx('flex-none text-[20px] font-normal leading-none text-subtle', open && 'pt-0.5')}
        >
          {open ? '−' : '+'}
        </span>
      </button>
      {/* Native `hidden`, not a conditional unmount: a closed accordion used to remove the answer
          from the DOM entirely, so a crawler that does not click (or does not run JS at all) saw
          a question with no answer under it -- on the one page carrying FAQPage schema, whose
          own rule is that the structured data must match what the page actually shows. `hidden`
          keeps the text present and gives the same "not shown" result visually and to the
          accessibility tree, without the SSR gap. */}
      {/* mockups/faq.html:189 `.faq p{font-size:15px;line-height:1.62;max-width:66ch;margin-top:11px}`.
          The answer sits on the same left edge as its question (no horizontal padding), the
          measure is capped at 66ch rather than by the container, and the row closes with the
          same 16px it opened with: `pb-4` minus the 5px the 11px top margin already spends. */}
      <div className="-mt-[5px] pb-4" hidden={!open}>
          <div className="max-w-[66ch] text-body leading-relaxed text-muted">
            <Answer item={item} />
          </div>
        </div>
    </div>
  );
}

export default function Faq() {
  const [search, setSearch] = React.useState('');
  const [activeCategory, setActiveCategory] = React.useState<string | null>(null);

  const filtered = React.useMemo(() => {
    let items = FAQS;
    if (activeCategory) items = items.filter((i) => i.category === activeCategory);
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(
        (i) =>
          i.question.toLowerCase().includes(q) ||
          plainAnswer(i).toLowerCase().includes(q),
      );
    }
    return items;
  }, [search, activeCategory]);

  return (
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'FAQ' }]}
      breadcrumbsWidth="6xl"
    >
      <Seo
        title="FAQ"
        description="The packs, the payment, and the guarantees. Common questions about Mumchimp."
        jsonLd={graph(
          faqPageNode(FAQS.map((item) => ({ question: item.question, answer: plainAnswer(item) }))),
          breadcrumbNode([
            { name: 'Mumchimp', path: '/' },
            { name: 'FAQ', path: '/faq' },
          ]),
        )}
      />

      {/* `width="6xl"`, not the default 4xl. FAQ was the only content page on the site left on
          the 896px column: how-it-works/kill-log/pack-detail run 1152px (6xl), home/sample/ideas
          run 1280px (7xl). At any desktop width the 896px column sits centred with a visibly
          wide empty gutter on both sides while every other page's wider column reads as starting
          near the true left edge -- that gap, not a text-align rule, is what read as "FAQ is
          centred, the rest of the pages look left-aligned" (confirmed via blocks.tsx:33 BAND_WIDTH
          + a width audit across all 14 public pages, 2026-08-09). 6xl matches the nearest sibling
          page type (a single column of list content), not the wider catalogue/showcase pages. */}
      <PageHero
        eyebrow="FAQ"
        title="Common questions."
        lead="What you’re buying, how it arrives, what we do and don’t promise."
        width="6xl"
      />

      {/* Search, filters and the answers they filter, in ONE band.
          UPDATE 2026-08-09: the band is back to 6xl, and PageHero above now matches it
          explicitly (`width="6xl"`), not because the 2026-08-06 fix below was wrong but because
          it solved the wrong mismatch. FAQ at 4xl was internally consistent (hero and body shared
          one left edge) but was still the single narrowest column on the site -- every other page
          runs 6xl or 7xl (see the width audit in `blocks.tsx:33`'s BAND_WIDTH usage) -- so at any
          desktop viewport FAQ's 896px column sat centred with a wide empty gutter either side
          while the rest of the site's wider columns read as starting near the true left edge.
          That, not a `text-align` rule, is what read as "FAQ is centred, the rest of the pages
          look left-aligned."
          Widening the band would reopen the exact bug the 2026-08-06 pass fixed -- a ~110-char
          answer measure -- if the answer text scaled with it, so it doesn't: the search box,
          filters and accordion are now wrapped in their own `max-w-3xl` below, the same
          band-decides-the-edge / inner-div-decides-the-line-length split `PageHero` already uses
          for its own headline (blocks.tsx:88-90). The band sets where the column starts, matching
          every other page; the inner wrapper keeps the line short enough to read.
          Split: the controls and the list were two `SectionBand`s, and a band always draws
          `border-b` (blocks.tsx:47->59). That put a full-bleed rule between the filter chips and
          the rows they filter, i.e. a page-wide divider announcing a new section directly between
          a control and its own result. They are one section; the split existed only to get
          different bottom padding -- still true, still one band. */}
      <SectionBand bg="white" width="6xl" className="!pt-0 !pb-16">
        <div>
          {/* The search box is OURS, not the mockup's: mockups/faq.html:334 opens straight on the
              chips. It is kept because it is a working feature, and it is capped at 470px because
              that is the widest input the drawing has anywhere (`.emailbox form{max-width:470px}`,
              mockups/faq.html:193). Everything below it now runs the full 1080px band, as the
              mockup does: line length is held by `max-w-[66ch]` on the answer itself
              (mockups/faq.html:189), not by squeezing the whole column to 3xl. */}
          <div className="max-w-[470px]">
            <SearchInput
              label="Search FAQs"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search FAQs…"
            />
          </div>

          {/* Category filters. `chipClasses` -- the same control the kill log and the shelf's
              facet bar render, which this page used to draw square and tinted instead.
              `mt-[18px]`: mockups/faq.html:146 `.chips{gap:8px;margin:18px 0}`. */}
          <div className="chips">
            <button
              type="button"
              onClick={() => setActiveCategory(null)}
              aria-pressed={!activeCategory}
              className="chip"
            >
              All
            </button>
            {CATEGORIES.map((cat) => (
              <button
                key={cat.key}
                type="button"
                onClick={() => setActiveCategory(cat.key)}
                aria-pressed={activeCategory === cat.key}
                className="chip"
              >
                {cat.label}
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="py-12 text-center">
              <p className="lede">No questions match &ldquo;{search}&rdquo;.</p>
              <button
                type="button"
                onClick={() => { setSearch(''); setActiveCategory(null); }}
                className={buttonClasses({ variant: 'secondary', className: 'mt-3' })}
              >
                Clear search
              </button>
            </div>
          ) : (
            /* THE DRAWING'S `.faq` LIST (`mockups/faq.html:184`), which has no box: the rows are a
               plain run of rules on the page. The wrapper drew `rounded-md border border-border`
               around them, which contradicted the note in `AccordionItem` directly below saying
               the list is not a bordered card. */
            <div className="faq mt-6">
              {filtered.map((item, i) => (
                <AccordionItem key={i} item={item} defaultOpen={i === 0} />
              ))}
            </div>
          )}
        </div>
      </SectionBand>

      {/* Support block -- elevated, right after the accordions. `width="6xl"` to match the band
          above, not because this content needs the room (the card inside is deliberately
          `mx-auto max-w-md`, a centred call-out, unaffected by the band width) but so the page
          doesn't reintroduce a second distinct container width of its own. */}
      {/* THE DRAWING'S SUPPORT BAR (`mockups/faq.html:342`): one full-width card, the heading and
          a mono line on the left, the button on the right. It was a 448px card floating in the
          middle of a grey band, which on a 1440px screen read as an unfinished section. */}
      <SectionBand bg="white" width="6xl" className="!pt-0 !pb-12">
        <div className="card mt-[30px] flex flex-wrap items-center justify-between gap-5 px-[var(--pad)] py-[22px]">
          <div>
            <h2 className="sub">A human reads every email</h2>
            <p className="mono mt-[7px]">
              <a href={`mailto:${LEGAL.supportEmail}`} className={textLinkClass()}>
                {LEGAL.supportEmail}
              </a>{' '}
              · replies in under 1 business day
            </p>
          </div>
          <Link href="/" className={buttonClasses({ variant: 'secondary' })}>
            Browse the catalogue
          </Link>
        </div>
      </SectionBand>

      {/* THE CLOSING BLOCK (`mockups/faq.html`, `.closing`). The page ended on the support card,
          so a reader who had their question answered was handed an email address and nothing to
          do next. The drawing ends every page on a 2px ink rule, a question, and two routes. */}
      <SectionBand bg="white" width="6xl" className="!pt-0 !pb-16">
        <div className="closing">
          <h2 className="sec">Still deciding?</h2>
          <p>
            Read a complete pack first. No payment, no email, no account.
          </p>
          <div className="ctarow">
            <Link href="/sample" className="btn">
              {SITE_COPY.sampleLink}
              <Icon name="arrowRight" size={14} />
            </Link>
            <Link href="/how-it-works" className="btn ghost">
              See how the filter works
            </Link>
          </div>
        </div>
      </SectionBand>
    </MarketingLayout>
  );
}
