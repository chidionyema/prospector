import React from 'react';
import Link from 'next/link';
import MarketingLayout from './MarketingLayout';
import { SectionBand, CtaBand } from './blocks';
import { Seo } from '@/components/Seo';

/**
 * Shell for the E30-005 evergreen guides (WR-037). Pure static editorial: no user data, no API, so
 * the pages stay SSG and Pact-free. Same voice + lexicon guardrails as the rest of the marketing
 * surface (the conformance gate scopes `src/pages/guides/` into MARKETING_SURFACE), so qualify
 * "verified" ("verified identity"/"verified introduction"), keep custody on the bank, and no dashes.
 *
 * These guides chase existing buyer-intent long-tail ("how to get a warm introduction to a [role]")
 * and end on a single honest CTA back into the product. They are a small cornerstone, NOT a content
 * engine (that is deferred, D-109).
 */
export function GuideLayout({
  title,
  description,
  heading,
  lead,
  children,
}: {
  title: string;
  description: string;
  heading: React.ReactNode;
  lead: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <MarketingLayout>
      <Seo title={title} description={description} />

      <SectionBand bg="surface" width="2xl" className="py-12 sm:py-16">
        <article>
          <p className="mb-6 text-small">
            <Link href="/guides" className="text-muted hover:text-text">
              Guides
            </Link>
          </p>
          <h1 className="text-balance text-display font-semibold tracking-tight text-text">{heading}</h1>
          <p className="mt-5 text-pretty text-h2 font-normal leading-relaxed text-text/70">{lead}</p>
          <div className="mt-10 space-y-8">{children}</div>
        </article>
      </SectionBand>

      <CtaBand
        title="Reach the people you can't get to cold."
        lead="Fund a proposal for a warm introduction, or offer the introductions only you can make."
        primary={{ href: '/register?role=Buyer', label: 'Start an introduction' }}
        secondary={{ href: '/how-it-works', label: 'See how it works' }}
      />
    </MarketingLayout>
  );
}

/** A guide sub-heading + its prose, with consistent rhythm. */
export function GuideSection({
  title,
  children,
}: {
  title: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-h1 font-semibold tracking-tight text-text">{title}</h2>
      <div className="space-y-4 text-body leading-relaxed text-muted">{children}</div>
    </section>
  );
}

/** A bulleted list inside a guide section. */
export function GuideList({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="list-disc space-y-2 pl-5 text-body leading-relaxed text-muted">
      {items.map((it, i) => (
        <li key={i}>{it}</li>
      ))}
    </ul>
  );
}
