import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, SectionBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { LEGAL } from '@/lib/config';
import { FAQS, isLink, plainAnswer, type FaqItem } from '@/lib/faqContent';
import { breadcrumbNode, faqPageNode, graph } from '@/lib/seo/schema';

/** One answer's segments as prose. */
function Answer({ item }: { item: FaqItem }) {
  return (
    <>
      {item.answer.map((segment, i) => {
        if (!isLink(segment)) return <React.Fragment key={i}>{segment}</React.Fragment>;
        const className = 'text-primary font-bold hover:underline';
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
    <div className="border border-border bg-surface transition-colors">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-4 p-5 text-left"
      >
        <h2 className="text-base font-bold text-text leading-snug pr-8">{item.question}</h2>
        <Icon
          name="arrowRight"
          size={16}
          className={cx(
            'flex-none text-muted transition-transform',
            open && 'rotate-90',
          )}
        />
      </button>
      {open && (
        <div className="px-5 pb-5 -mt-1">
          <div className="text-sm leading-relaxed text-text/75">
            <Answer item={item} />
          </div>
          {/* Was this helpful? */}
          <div className="mt-4 flex items-center gap-3 border-t border-border/60 pt-3">
            <span className="text-[11px] text-muted">Was this helpful?</span>
            <button
              type="button"
              onClick={() => setFeedback(feedback === 'up' ? null : 'up')}
              className={cx(
                'text-sm transition-colors',
                feedback === 'up' ? 'text-success' : 'text-muted hover:text-text',
              )}
              aria-label="Yes"
            >
              👍
            </button>
            <button
              type="button"
              onClick={() => setFeedback(feedback === 'down' ? null : 'down')}
              className={cx(
                'text-sm transition-colors',
                feedback === 'down' ? 'text-warning' : 'text-muted hover:text-text',
              )}
              aria-label="No"
            >
              👎
            </button>
          </div>
        </div>
      )}
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

  const query = search.trim().toLowerCase();

  return (
    <MarketingLayout>
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

      <PageHero
        eyebrow="FAQ"
        title={<span className="leading-tight tracking-tighter">Common questions.</span>}
        lead="What you're buying, how it's delivered, and what we do and don't promise."
      />

      {/* Search + sticky category pills */}
      <SectionBand bg="white" width="6xl" className="!pt-0 !pb-4">
        <div className="relative">
          <Icon name="search" size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search FAQs…"
            className="w-full border border-border bg-surface py-3 pl-11 pr-4 text-sm text-text outline-none transition-colors focus:border-primary/40"
          />
        </div>

        {/* Sticky category pills */}
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setActiveCategory(null)}
            className={cx(
              'px-3 py-1.5 text-xs font-semibold transition-colors border',
              !activeCategory
                ? 'border-primary bg-primary/10 text-text'
                : 'border-border bg-surface text-muted hover:border-text/20',
            )}
          >
            All
          </button>
          {CATEGORIES.map((cat) => (
            <button
              key={cat.key}
              type="button"
              onClick={() => setActiveCategory(cat.key)}
              className={cx(
                'px-3 py-1.5 text-xs font-semibold transition-colors border',
                activeCategory === cat.key
                  ? 'border-primary bg-primary/10 text-text'
                  : 'border-border bg-surface text-muted hover:border-text/20',
              )}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </SectionBand>

      {/* FAQ accordions */}
      <SectionBand bg="white" width="6xl" className="!pt-0 !pb-16">
        {filtered.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-sm text-muted">No questions match &ldquo;{search}&rdquo;.</p>
            <button
              type="button"
              onClick={() => { setSearch(''); setActiveCategory(null); }}
              className="mt-2 text-sm font-semibold text-primary hover:underline"
            >
              Clear search
            </button>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {filtered.map((item, i) => (
              <AccordionItem key={i} item={item} defaultOpen={i === 0} />
            ))}
          </div>
        )}
      </SectionBand>

      {/* Support block -- elevated, right after the accordions */}
      <SectionBand bg="bg" width="6xl" className="!py-12">
        <div className="mx-auto max-w-md border border-border bg-surface p-6">
          <div className="flex items-center gap-3 mb-4">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-success/10 text-success">
              <Icon name="mail" size={14} />
            </span>
            <h4 className="font-bold text-sm text-text">A human reads every email</h4>
          </div>
          <div className="space-y-3 font-mono text-xs">
            <div className="flex flex-col border-b border-border/60 pb-3">
              <span className="text-muted uppercase font-bold tracking-tight mb-1">Email</span>
              <a href={`mailto:${LEGAL.supportEmail}`} className="font-bold text-primary break-all hover:underline">{LEGAL.supportEmail}</a>
            </div>
            <div className="flex flex-col">
              <span className="text-muted uppercase font-bold tracking-tight mb-1">Response Time</span>
              <span className="font-bold text-text">&lt; 1 business day</span>
            </div>
          </div>
          <Link
            href="/"
            className="mt-5 inline-flex items-center gap-2 bg-primary px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary-hover"
          >
            Browse the catalogue <Icon name="arrowRight" size={14} />
          </Link>
        </div>
      </SectionBand>
    </MarketingLayout>
  );
}
