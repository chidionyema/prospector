import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { TOS_VERSION } from '@/lib/config';

interface LegalDocProps {
  title: string;
  /** Doc version string — defaults to the registration-recorded TOS_VERSION (L-04/L-05). */
  version?: string;
  /** Hide the "interim, pending counsel" banner only once counsel has signed the copy off. */
  interim?: boolean;
  children: React.ReactNode;
}

/**
 * Shared shell for the static legal surfaces (/terms, /privacy, /refund). Uses the public
 * MarketingLayout so the legal pages share the same nav + footer as the rest of the store
 * (rather than the authenticated app shell, which is wrong for a public legal page).
 *
 * These are INTERIM beta-stage documents grounded in docs/legal/LEGAL-DECISIONS-LOG.md and are
 * explicitly pending final legal review (E12 / launch task #17). The banner says so honestly —
 * a clickwrap that links to clearly-marked interim terms beats a checkbox pointing at nothing.
 * Semantic tokens only (UI-STANDARDS); no raw palette, no dangerouslySetInnerHTML.
 */
export default function LegalDoc({ title, version = TOS_VERSION, interim = true, children }: LegalDocProps) {
  return (
    <MarketingLayout>
      <Seo title={title} />
      <div className="mx-auto max-w-2xl px-6 md:px-8">
        <article className="space-y-10 py-12 md:py-16">
          <header className="space-y-6">
            <div className="space-y-2">
              <h1 className="text-4xl font-bold text-text tracking-tight leading-none">{title}</h1>
              <p className="text-xs font-bold font-mono text-muted uppercase tracking-widest">Version {version}</p>
            </div>
            {interim && (
              <div className="rounded-lg border border-border bg-bg/50 px-6 py-5 text-sm leading-relaxed text-muted shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
                <strong className="text-text font-bold">Interim beta terms.</strong> This document reflects how the
                platform actually works today and is pending final review by our legal counsel. We&apos;ll
                post a new version here if anything material changes.
              </div>
            )}
          </header>
          <div className="space-y-8">{children}</div>
          <div className="border-t border-border pt-8 mt-12">
            <Link href="/" className="text-sm font-bold text-primary hover:underline flex items-center gap-2 uppercase tracking-wide">
              &larr; Back to home
            </Link>
          </div>
        </article>
      </div>
    </MarketingLayout>
  );
}

/** Section heading inside a legal doc. */
export function LegalHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xl font-bold text-text pt-4 tracking-tight leading-tight">{children}</h2>;
}

/** Body paragraph inside a legal doc. */
export function LegalText({ children }: { children: React.ReactNode }) {
  return <p className="text-base leading-relaxed text-text/80">{children}</p>;
}

/** Bulleted list inside a legal doc. */
export function LegalList({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="list-disc space-y-3 pl-5 text-base leading-relaxed text-text/80">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}
