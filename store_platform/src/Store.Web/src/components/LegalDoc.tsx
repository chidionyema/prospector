import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { TOS_VERSION } from '@/lib/config';

interface LegalDocProps {
  title: string;
  /** Doc version string, defaults to the registration-recorded TOS_VERSION (L-04/L-05). */
  version?: string;
  /** Show the "interim, pending counsel" banner. Off by default; see note below. */
  interim?: boolean;
  children: React.ReactNode;
}

/**
 * Shared shell for the static legal surfaces (/terms, /privacy, /refund). Uses the public
 * MarketingLayout so the legal pages share the same nav + footer as the rest of the store
 * (rather than the authenticated app shell, which is wrong for a public legal page).
 *
 * Founder decision 2026-08-07 (pre-launch commercial-readiness pass): telling a paying buyer
 * their terms are unfinished is a self-inflicted wound, not honesty; a buyer reads "pending
 * legal counsel review" as "this contract may not hold," which is worse than no caveat at all.
 * These documents ship as final as of this date, grounded in docs/legal/LEGAL-DECISIONS-LOG.md.
 * `interim` stays available so a specific page can re-add the banner if a real draft goes out
 * for review before it is finalised, but nothing sets it now. Semantic tokens only
 * (UI-STANDARDS); no raw palette, no dangerouslySetInnerHTML.
 */
export default function LegalDoc({ title, version = TOS_VERSION, interim = false, children }: LegalDocProps) {
  return (
    <MarketingLayout>
      <Seo title={title} />
      <div className="mx-auto max-w-2xl px-6 md:px-8">
        <article className="space-y-10 py-12 md:py-16">
          <header className="space-y-6">
            <div className="space-y-2">
              <h1 className="text-h1 font-semibold text-text">{title}</h1>
       <p className="text-caption font-medium text-muted">Version {version}</p>
            </div>
            {interim && (
              <div className="rounded-md border border-border bg-bg/50 px-6 py-5 text-meta leading-relaxed text-muted">
                <strong className="text-text font-semibold">Interim beta terms.</strong> This document reflects how the
                platform actually works today and is pending final review by our legal counsel. We&apos;ll
                post a new version here if anything material changes.
              </div>
            )}
          </header>
          <div className="space-y-8">{children}</div>
          <div className="border-t border-border pt-8 mt-12">
            <Link href="/" className="flex items-center gap-2 text-meta font-semibold text-accent transition-colors hover:text-accent-hover">
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
  return <h2 className="text-h2 font-semibold text-text pt-4">{children}</h2>;
}

/** Body paragraph inside a legal doc. */
export function LegalText({ children }: { children: React.ReactNode }) {
  return <p className="text-body leading-relaxed text-muted">{children}</p>;
}

/** Bulleted list inside a legal doc. */
export function LegalList({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="list-disc space-y-3 pl-5 text-body leading-relaxed text-muted">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}
