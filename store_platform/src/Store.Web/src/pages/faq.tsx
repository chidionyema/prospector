import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, SectionBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { buttonClasses, chipClasses, Icon, SearchInput, textLinkClass } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { LEGAL } from '@/lib/config';
import { FAQS, isLink, plainAnswer, type FaqItem } from '@/lib/faqContent';
import { track } from '@/lib/analytics';
import { breadcrumbNode, faqPageNode, graph } from '@/lib/seo/schema';

/**
 * A stable key for one question, for the helpfulness beacon.
 *
 * The question TEXT, not its position. The list is ordered by purchase blocker and that order has
 * already changed once; keyed by index, every vote recorded before a reorder would silently start
 * describing whichever question moved into that slot.
 */
function questionSlug(question: string): string {
  return question.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48);
}

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
  const [feedback, setFeedback] = React.useState<'up' | 'down' | null>(null);

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
        <h2 className="text-body font-semibold tracking-[-0.014em] text-text leading-snug">{item.question}</h2>
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
          {/*
            Was this helpful? Two words, not two emoji.
            `pricing.tsx` already stated the rule when it stopped rendering the pack-contents
            emoji: each one is a different vendor's artwork per OS, and it is the loudest thing on
            a page about a professional research product. A thumbs-up next to a paragraph about the
            refund policy is exactly that. Words also give the control a visible label rather than
            an `aria-label` that only a screen reader ever hears.

            IT NOW REPORTS. Until 2026-08-18 the click set a piece of React state that nothing read
            and nothing sent, so the page carried 26 buttons that collected a vote we then threw
            away on the next navigation. The founder wants the control, so the fix is to make it
            true rather than to remove it: each vote fires the first-party beacon under
            `faq_helpful`, keyed by a SLUG of the question rather than its index, because step 7
            reordered this list and an index would have re-pointed every historic vote at a
            different question.

            The beacon fires only when a vote is CAST. Clicking the same answer again clears the
            choice, and an un-vote sends nothing: there is no "retract" event, and re-firing the
            same name on the way out would count the vote twice.
          */}
          <div className="mt-4 flex items-center gap-2 border-t border-border pt-3">
            <span className="text-caption text-muted">Was this helpful?</span>
            {(['up', 'down'] as const).map((choice) => (
              <button
                key={choice}
                type="button"
                onClick={() => {
                  const next = feedback === choice ? null : choice;
                  setFeedback(next);
                  if (next) track('faq_helpful', `${questionSlug(item.question)}:${next}`);
                }}
                aria-pressed={feedback === choice}
                className={chipClasses({ selected: feedback === choice })}
              >
                {choice === 'up' ? 'Yes' : 'No'}
              </button>
            ))}
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
          the 896px column: how-it-works/kill-log/pack-detail run 1152px (6xl), home/sample/collections
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
          <div className="mt-[18px] flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveCategory(null)}
              aria-pressed={!activeCategory}
              className={chipClasses({ selected: !activeCategory })}
            >
              All
            </button>
            {CATEGORIES.map((cat) => (
              <button
                key={cat.key}
                type="button"
                onClick={() => setActiveCategory(cat.key)}
                aria-pressed={activeCategory === cat.key}
                className={chipClasses({ selected: activeCategory === cat.key })}
              >
                {cat.label}
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-meta text-muted">No questions match &ldquo;{search}&rdquo;.</p>
              <button
                type="button"
                onClick={() => { setSearch(''); setActiveCategory(null); }}
                className={buttonClasses({ variant: 'secondary', className: 'mt-3' })}
              >
                Clear search
              </button>
            </div>
          ) : (
            // The list owns the box; each row owns only its bottom rule (see `AccordionItem`).
            <div className="mt-6 overflow-hidden rounded-md border border-border">
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
      <SectionBand bg="bg" width="6xl" className="!py-12">
        <div className="mx-auto max-w-md rounded-card border border-border bg-surface p-6">
          <div className="flex items-center gap-3 mb-4">
            <span className="flex h-8 w-8 items-center justify-center rounded-sm bg-success/10 text-success">
              <Icon name="mail" size={14} />
            </span>
            {/* `h2`, not `h4`. This is the last top-level section of the page and its heading sits
                at the same rank as the accordion questions above it; as an `h4` under an `h1` and a
                run of `h2`s it made the page's outline jump 2 -> 4, which a screen reader announces
                as two missing levels of structure that a sighted reader never sees. Measured on the
                rendered page 2026-08-13. Its size is set by `text-meta`, so nothing on screen moves. */}
            <h2 className="font-semibold text-meta text-text">A human reads every email</h2>
          </div>
          <div className="space-y-3 text-caption">
            <div className="flex flex-col border-b border-border pb-3">
              <span className="text-muted font-semibold tracking-tight mb-1">Email</span>
              <a href={`mailto:${LEGAL.supportEmail}`} className="inline-block break-all py-[13px] font-medium text-accent transition-colors hover:text-accent-hover">{LEGAL.supportEmail}</a>
            </div>
            <div className="flex flex-col">
              <span className="mb-1 text-caption font-medium text-subtle">Response time</span>
              <span className="text-meta font-medium text-text">&lt; 1 business day</span>
            </div>
          </div>
          <Link
            href="/"
            className={buttonClasses({ className: 'mt-5' })}
          >
            Browse the catalogue <Icon name="arrowRight" size={14} />
          </Link>
        </div>
      </SectionBand>

      {/* THE CLOSING BLOCK (`mockups/faq.html`, `.closing`). The page ended on the support card,
          so a reader who had their question answered was handed an email address and nothing to
          do next. The drawing ends every page on a 2px ink rule, a question, and two routes. */}
      <SectionBand bg="white" width="6xl" className="!pt-0 !pb-16">
        <div className="mt-12 border-t-2 border-text pt-9">
          <h2 className="text-h2 font-semibold text-text">Still deciding?</h2>
          <p className="mt-3.5 mb-[22px] max-w-[56ch] text-body leading-relaxed text-muted">
            Read a complete pack first. No payment, no email, no account.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link href="/sample" className={buttonClasses({ size: 'lg' })}>
              Read a full pack free
              <Icon name="arrowRight" size={14} />
            </Link>
            <Link
              href="/how-it-works"
              className={buttonClasses({ variant: 'secondary', size: 'lg' })}
            >
              See how the filter works
            </Link>
          </div>
        </div>
      </SectionBand>
    </MarketingLayout>
  );
}
