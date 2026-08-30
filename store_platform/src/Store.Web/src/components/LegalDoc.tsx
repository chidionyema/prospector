import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { TOS_VERSION } from '@/lib/config';
import DocRail, { type DocSectionRef } from '@/components/marketing/DocRail';
import { buttonClasses } from '@/components/ui';

interface LegalDocProps {
  title: string;
  /**
   * One sentence under the title, at `.lede.big` (`mockups/refund.html`). The drawing gives every
   * legal page a plain-language summary above the clauses, so a reader gets the answer before the
   * contract. Optional: a page with no honest one-line summary should not invent one.
   */
  lede?: string;
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
export default function LegalDoc({ title, lede, version = TOS_VERSION, interim = false, children }: LegalDocProps) {
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
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: title }]}
      breadcrumbsWidth="6xl"
    >
      <Seo title={title} />
      {/* THE DRAWING'S LEGAL GRID (`mockups/refund.html`, `.legal{grid-template-columns:1fr 230px;
          gap:34px;align-items:start}`) inside the site's one frame, `.wrap{max-width:1080px;
          padding:0 20px}`.

          TWO CHANGES OF SUBSTANCE. The band was `max-w-6xl px-6 md:px-8`, a 1152px measure at a
          24/32px gutter, so the legal pages were 72px wider than the header above them and their
          left edge missed the logo. And the clause rail sat on the LEFT at 16rem: the drawing puts
          it on the RIGHT at 230px, which is what keeps the document itself starting at the same x
          as every other page's content. The article now comes first in the DOM too, so a screen
          reader and a keyboard both reach the contract before the index of it.

          The grid is the drawing's `.legal` class now, not utilities holding the same two columns
          at different numbers. It had to be: `mumchimp.css` sits in `layer(components)` and Tailwind
          utilities sit above it, so any utility that also sets `grid-template-columns` wins and the
          class is inert. Both collapse to one column at 860px, and `DocRail` now appears at 861px
          to match, so there is no width where the rail is hidden but its column is still reserved. */}
      <div className="mx-auto max-w-[1080px] px-5">
        <div className="legal pt-3.5 pb-16">
          <article className="space-y-10">
            <header className="pagetop space-y-6">
              <div className="space-y-2">
                <h1>{title}</h1>
                {/* Was "Version 2026-06-15", which is a build artefact as far as a buyer is
                    concerned: the one thing a reader wants from the head of a legal document is
                    whether it is current, and an ISO string beside the word "version" does not
                    answer that until they decode it. The version identifier stays, because it is
                    what the account's consent record stores and a customer disputing a term needs
                    to be able to match the two. */}
                {/* Each half is its own non-wrapping span with the middot as the only break point.
                    As one string this line broke inside the identifier at 390px -- measured on
                    /terms 2026-08-13, it rendered "version 2026-06-" / "15" -- and a version a
                    customer is meant to match against their consent record cannot be split across
                    two lines mid-token. `flex-wrap` lets the two halves stack instead. */}
                <p className="flex flex-wrap gap-x-2 font-mono text-caption text-subtle">
                  {inForce && <span className="whitespace-nowrap">in force since {inForce} &middot;</span>}
                  <span className="whitespace-nowrap">version {version}</span>
                </p>
              </div>
              {/* `.lede.big` (17.5px, 62ch): the plain-language answer above the contract. */}
              {lede && <p className="lede big">{lede}</p>}
              {interim && (
                <div className="rounded-md border border-border bg-bg/50 px-6 py-5 text-meta leading-relaxed text-muted">
                  <strong className="text-text font-semibold">Interim beta terms.</strong> This document reflects how the
                  site actually works today and is pending final review by our legal counsel. We&apos;ll
                  post a new version here if anything material changes.
                </div>
              )}
            </header>
            <div className="space-y-8">{withAnchors}</div>
            {/* THE CLOSING BLOCK (`mockups/refund.html`, `.closing{border-top:2px solid var(--ink);
                margin-top:46px;padding:34px 0 0}`). It was a single "Back to home" text link under
                a hairline.

                The second button pointed at `/faq` until 2026-08-21, on the reasoning that "the
                catalogue is already one click away in the crumb above and in the header". The crumb
                and the header both go to `/`, which is the top of a long marketing page, and the
                header nav has no shelf link at all -- it carries Categories, How it works, Kill log,
                FAQ, Account. So these three legal pages were the estate's only dead ends: a reader
                who checked the refund policy before buying could reach the FAQ and the free sample
                and no product. `/#catalog` is the shelf itself. Graded by FR3 in
                `e2e/first-run.spec.ts`. */}
            <div className="closing">
              <h2 className="sec">
                Read one free before you buy anything.
              </h2>
              <p>
                {/* "pack", the drawing's word and the site's (`mockups/refund.html`). */}
                A complete pack, unredacted. No payment, no email, no account.
              </p>
              <div className="ctarow">
                <Link href="/sample" className="btn">
                  Read the free report
                </Link>
                <Link href="/#catalog" className="btn ghost">
                  Browse the packs
                </Link>
              </div>
            </div>
          </article>
          <DocRail sections={sections} eyebrow="clauses" className="min-[861px]:pt-1" />
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
    <h2 id={id} className="scroll-mt-24 pt-4 text-h3 font-semibold text-text">
      {children}
    </h2>
  );
}

/** Body paragraph inside a legal doc. */
export function LegalText({ children }: { children: React.ReactNode }) {
  // `max-w-[68ch]` and `leading-[1.68]`: the drawing's `.legal p` (`mockups/refund.html`). The
  // measure lives on the paragraph now rather than on a `max-w-2xl` wrapper, so the clause rail
  // sits beside a document whose own text sets its width.
  return <p className="lede">{children}</p>;
}

/** Bulleted list inside a legal doc. */
export function LegalList({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="max-w-[68ch] list-disc space-y-3 pl-5 text-body leading-[1.68] text-muted">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}
