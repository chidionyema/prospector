import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { LEGAL } from '@/lib/config';
import { FAQS, isLink, plainAnswer, type FaqItem } from '@/lib/faqContent';
import { breadcrumbNode, faqPageNode, graph } from '@/lib/seo/schema';

/**
 * Render one answer's segments as prose. The segments come from `lib/faqContent.ts`, which is also
 * what the FAQPage structured data below serialises, that shared source is what keeps the schema
 * and the visible answer identical, which is the condition Google requires of FAQ markup.
 *
 * A `mailto:` link is a plain anchor; an internal route gets `next/link` so it client-navigates.
 */
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

export default function Faq() {
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

      <Section
        bg="white"
        width="7xl"
        title={<span className="font-black">About the packs</span>}
      >
        <div className="space-y-6 mt-12 md:mt-16">
          {FAQS.filter((item) => item.category === 'packs').map((item, i) => (
            <div key={i} className="bg-white border border-border p-8 rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] transition-standard hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] group">
              <h2 className="text-lg font-black text-text mb-4 leading-tight group-hover:text-primary transition-standard">{item.question}</h2>
              <div className="text-base text-text/80 leading-relaxed"><Answer item={item} /></div>
            </div>
          ))}
        </div>
      </Section>

      <Section
        bg="bg"
        width="7xl"
        title={<span className="font-black">Payment &amp; access</span>}
      >
        <div className="space-y-6 mt-12 md:mt-16">
          {FAQS.filter((item) => item.category === 'payment').map((item, i) => (
            <div key={i} className="bg-white border border-border p-8 rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] transition-standard hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] group">
              <h2 className="text-lg font-black text-text mb-4 leading-tight group-hover:text-primary transition-standard">{item.question}</h2>
              <div className="text-base text-text/80 leading-relaxed"><Answer item={item} /></div>
            </div>
          ))}
        </div>
      </Section>

      <Section
        bg="white"
        width="7xl"
        title={<span className="font-black">The vetting process</span>}
      >
        <div className="space-y-6 mt-12 md:mt-16">
          {FAQS.filter((item) => item.category === 'process').map((item, i) => (
            <div key={i} className="bg-white border border-border p-8 rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] transition-standard hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] group">
              <h2 className="text-lg font-black text-text mb-4 leading-tight group-hover:text-primary transition-standard">{item.question}</h2>
              <div className="text-base text-text/80 leading-relaxed"><Answer item={item} /></div>
            </div>
          ))}
        </div>
      </Section>

      <Section bg="white" width="7xl">
        <aside className="space-y-6 max-w-sm mx-auto">
          <div className="bg-white border border-border p-6 rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] transition-standard hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] group">
            <h4 className="font-bold text-[10px] uppercase tracking-widest text-text mb-4">Contact Support</h4>
            <div className="space-y-4 font-mono text-[11px]">
              <div className="flex flex-col border-b border-border/60 pb-4">
                <span className="text-muted uppercase font-bold tracking-tight mb-1">Email</span>
                <a href={`mailto:${LEGAL.supportEmail}`} className="font-bold text-primary break-all hover:underline">{LEGAL.supportEmail}</a>
              </div>
              <div className="flex flex-col">
                <span className="text-muted uppercase font-bold tracking-tight mb-1">Response Time</span>
                <span className="font-bold text-text">&lt; 1 business day</span>
              </div>
            </div>
          </div>
        </aside>
      </Section>

      <CtaBand
        title="Browse the catalogue."
        lead=""
        primary={{ href: '/', label: 'Browse the packs' }}
      />
    </MarketingLayout>
  );
}
