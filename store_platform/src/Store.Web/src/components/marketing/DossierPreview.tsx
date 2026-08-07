import React from 'react';
import Link from 'next/link';
import { Icon, textLinkClass } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import report from '@/data/sample-report.json';

/*
  What the buyer is actually paying for, shown rather than described.

  The list above this says a pack contains a verification dossier. That is a noun, and the
  documented fear on a digital download page is paying £49 for a two-page Google Doc. So this
  shows the dossier itself: the real check names, the real verdicts, the real source domains
  from Report #00, the free sample. Nothing here is a mockup, it is the same JSON the /sample
  page renders in full, which is why one of the eight rows says the idea was pushed back.

  Keeping that row is the point. A preview showing eight green ticks would be a better advert
  and a worse claim, and the shop's whole pitch is that the checks can fail.
*/

type Source = { url: string; label: string };
type Check = { name: string; verdict: string; sources: Source[] };

const checks = report.checks as Check[];

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

export function DossierPreview() {
  return (
    <div className="mt-10 overflow-hidden rounded-md border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface2 px-5 py-4 md:px-7">
        <div>
          <p className="text-caption font-medium text-subtle">A real page from a real pack</p>
          <p className="mt-1 text-meta font-semibold text-text">
            {report.title}, the verification dossier
          </p>
        </div>
        {/* Not "{supported} of {total} survived" -- see the note on `/sample`. A fraction on a page
            that promises "listed only once it clears every check" reads as a failed exam, and this
            one sat inside a panel captioned "a real page from a real pack". Two facts, no
            denominator. */}
        <span className="font-mono text-caption text-subtle">
          {report.supported} cleared · {report.sourceCount} sources
        </span>
      </div>

      {/* Not a table: at phone width a table either scrolls sideways or crushes the check name,
          and the check name is the part that explains what was actually tested. */}
      <ul className="list-none divide-y divide-border p-0">
        {checks.map((check, i) => {
          const supported = check.verdict === 'supported';
          const domain = domainOf(check.sources[0]?.url ?? '');
          return (
            <li key={i} className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-5 py-3 md:px-7">
              {/* The glyph alone, not a glyph in a tinted disc. Eight coloured discs down the
                  left of the list read as a status dashboard; the verdict word beside each row is
                  what actually carries the meaning, and it is not encoded in hue alone. */}
              <Icon
                name={supported ? 'check' : 'warning'}
                size={14}
                className={cx('flex-none', supported ? 'text-success' : 'text-warning')}
              />
              <span className="min-w-0 flex-1 text-meta font-medium text-text">{check.name}</span>
              <span
                className={cx(
                  'font-mono text-caption',
                  supported ? 'text-success' : 'text-warning',
                )}
              >
                {supported ? 'Survived' : 'Pushed back'}
              </span>
              {/* A REAL ANCHOR, not a printed string.
                  This rendered the domain as a `<span>`, inside a panel whose footer said "every
                  source is a live link in the pack", on a home page whose headline promise is
                  "every claim links to its source". So the single page making that promise was the
                  one place on the site where a source could not be opened -- the reader had to buy
                  a pack, or at least leave for /sample, to test the claim the page had just made.
                  Now the claim is testable in place, which is the only kind of proof this shop's
                  argument accepts.

                  The `rel` and the -45deg `arrowRight` both copy `SourceChips` in `pages/sample.tsx`
                  deliberately: this site has one way of drawing "a source you can open", and a
                  second one invented here would make the same object look like two different kinds
                  of thing on two pages the reader visits back to back. There is no external-link
                  glyph in `ICON_MAP`; the rotated arrow IS the idiom.

                  `textLinkClass` rather than a hand-rolled hover rule: a phone never fires the
                  hover event, so an underline that is only drawn on hover leaves the one clickable
                  proof on this panel looking like printed text on exactly the devices that cannot
                  test it. */}
              {domain && (
                <a
                  href={check.sources[0].url}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className={textLinkClass(
                    cx(
                      'inline-flex w-full items-center gap-1.5 font-mono text-caption',
                      'md:w-auto md:min-w-[13rem] md:justify-end',
                    ),
                  )}
                >
                  <Icon name="arrowRight" size={11} className="-rotate-45 shrink-0" />
                  {domain}
                </a>
              )}
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-surface2 px-5 py-4 md:px-7">
        {/* Was "Every source is a live link in the pack" -- a promise about a file the reader has
            not bought, printed under eight sources they could not click. The domains above open
            now, so the sentence can describe what the reader is looking at. */}
        <p className="text-caption text-subtle">
          Those domains open. Every claim in every pack carries one.
        </p>
        <Link
          href="/sample"
          className="inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
        >
          Read a full dossier free
          <Icon name="arrowRight" size={14} />
        </Link>
      </div>
    </div>
  );
}
