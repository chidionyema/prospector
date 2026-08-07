import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { TOS_VERSION } from '@/lib/config';
import DocRail, { type DocSectionRef } from '@/components/marketing/DocRail';

interface LegalDocProps {
  title: string;
  /** Doc version string, defaults to the registration-recorded TOS_VERSION (L-04/L-05). */
  version?: string;
  /** Show the "interim, pending counsel" banner. Off by default; see note below. */
  interim?: boolean;
  children: React.ReactNode;
}

/** Flatten a heading's children to plain text, for the anchor id and the rail label. */
function nodeText(node: React.ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join('');
  if (React.isValidElement(node)) {
    return nodeText((node.props as { children?: React.ReactNode }).children);
  }
  return '';
}

/**
 * A stable anchor for a clause, derived from its own heading text.
 *
 * `s-` prefixed because every heading in these documents begins with its clause number, and a
 * bare leading digit is not a valid CSS custom-ident, so `#1-what-we-sell` cannot be selected.
 */
function clauseId(text: string): string {
  return `s-${text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`;
}

/**
 * "2026-06-15" as "15 June 2026", without going through `Date`.
 *
 * `new Date('2026-06-15')` parses as UTC midnight, so in any timezone west of UTC it formats as
 * the 14th: a legal document would print a different in-force date depending on where the reader
 * sits, and would disagree with itself between the server render and the client hydration. The
 * version string is already the three fields; splitting it is the whole job.
 */
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
function formatVersionDate(version: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(version);
  if (!match) return null;
  const month = MONTHS[Number(match[2]) - 1];
  if (!month) return null;
  return `${Number(match[3])} ${month} ${match[1]}`;
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
  /*
    THE CLAUSE RAIL.

    These are the three longest documents on the site (terms 175 lines, privacy 231, refund 162)
    and they rendered as one undivided 2xl column: a reader looking for the refund window, or the
    list of subprocessors, had no option but to scroll and scan. Legal copy is the one genre where
    nobody reads linearly and everybody arrives with a specific question, so navigation is not a
    nicety here, it is the only way the document gets used.

    The headings are collected from the children rather than declared twice. A hand-written table
    of contents beside a hand-written document is two lists that drift, and the one that drifts
    silently is the index: a clause renumbered in the copy and not in the index sends the reader to
    the wrong paragraph of a contract. Reading the real headings means the rail cannot be wrong.

    `DocRail` is the same component `/sample` uses, and reusing it is deliberate. The site had two
    layout primitives (a bordered card in a grid, and a paragraph), which is why every page read as
    the same page with different words. A second primitive that means "this is a long structured
    document, here is where you are in it" is worth having exactly once and using everywhere it is
    true.
  */
  const items = React.Children.toArray(children);
  const sections: DocSectionRef[] = [];
  const withAnchors = items.map((child, i) => {
    if (!React.isValidElement(child) || child.type !== LegalHeading) return child;
    const text = nodeText((child.props as { children?: React.ReactNode }).children);
    if (!text) return child;
    const id = clauseId(text);
    sections.push({ id, label: text });
    return React.cloneElement(child as React.ReactElement<LegalHeadingProps>, { id, key: `h-${i}` });
  });

  const inForce = formatVersionDate(version);

  return (
    <MarketingLayout>
      <Seo title={title} />
      {/* `6xl` and a grid: the rail is new width beside the document, not taken out of it, so the
          copy keeps the `max-w-2xl` measure it has always had. Below `lg` the rail does not render
          and this collapses to exactly the single column it was. */}
      <div className="mx-auto max-w-6xl px-6 md:px-8">
        <div className="py-12 md:py-16 lg:grid lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-12">
          <DocRail sections={sections} eyebrow="clauses" className="lg:pt-1" />
          <article className="max-w-2xl space-y-10">
            <header className="space-y-6">
              <div className="space-y-2">
                <h1 className="text-h1 font-semibold text-text">{title}</h1>
                {/* Was "Version 2026-06-15", which is a build artefact as far as a buyer is
                    concerned: the one thing a reader wants from the head of a legal document is
                    whether it is current, and an ISO string beside the word "version" does not
                    answer that until they decode it. The version identifier stays, because it is
                    what the account's consent record stores and a customer disputing a term needs
                    to be able to match the two. */}
                <p className="font-mono text-caption text-subtle">
                  {inForce ? `in force since ${inForce} · version ${version}` : `version ${version}`}
                </p>
              </div>
              {interim && (
                <div className="rounded-md border border-border bg-bg/50 px-6 py-5 text-meta leading-relaxed text-muted">
                  <strong className="text-text font-semibold">Interim beta terms.</strong> This document reflects how the
                  platform actually works today and is pending final review by our legal counsel. We&apos;ll
                  post a new version here if anything material changes.
                </div>
              )}
            </header>
            <div className="space-y-8">{withAnchors}</div>
            <div className="border-t border-border pt-8 mt-12">
              <Link href="/" className="flex items-center gap-2 text-meta font-semibold text-accent transition-colors hover:text-accent-hover">
                &larr; Back to home
              </Link>
            </div>
          </article>
        </div>
      </div>
    </MarketingLayout>
  );
}

interface LegalHeadingProps {
  children: React.ReactNode;
  /** Injected by `LegalDoc` so the clause rail can link to it. Never passed by a page. */
  id?: string;
}

/** Section heading inside a legal doc. `scroll-mt-24` clears the sticky header on a jump. */
export function LegalHeading({ children, id }: LegalHeadingProps) {
  return (
    <h2 id={id} className="scroll-mt-24 text-h2 font-semibold text-text pt-4">
      {children}
    </h2>
  );
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
