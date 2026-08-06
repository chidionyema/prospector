/**
 * The citation chip -- the one component that turns the brand's central claim into an artifact
 * the visitor can click.
 *
 * The pack page promises "a clickable source behind every claim" and, until this shipped,
 * rendered its sources as plain text (see `lib/citations.ts` for the measurement). A chip is
 * the right form because a citation is a *thing*, not a phrase: it has a boundary, it is
 * countable at a glance, and a row of them reads as evidence even before anything is clicked.
 *
 * DESIGN NOTES
 *
 * - No favicon. The obvious "favicon-bearing chip" implementation fetches
 *   `google.com/s2/favicons?domain=` per source, which would send every visitor's IP to Google
 *   on every pack page -- on a storefront whose privacy posture is deliberate enough to have a
 *   no-device-storage analytics branch. A link glyph plus the hostname carries the same
 *   "this is a real place on the web" signal with no third-party request.
 * - The hostname is the label, not the page title. It is the part a reader uses to judge
 *   provenance (`assets.publishing.service.gov.uk` vs someone's blog), and it is the part we
 *   actually have without a second fetch.
 * - `rel="nofollow"` because these are cited sources, not endorsements, and there are 51 of
 *   them on some packs.
 * - The chip is ink-on-surface with a hairline, NOT vermillion. Vermillion means "you can act
 *   here" (buy); a citation is evidence, so it takes the evidence voice. See the colour rule in
 *   specs/design-critique-2026-08-05.md §5. (Vermillion is now deleted from the palette outright;
 *   the rule survives it.)
 * - Brand v3 (2026-08-06): rounded corners and `--muted` ink, per spec §6.11. The square chip was
 *   the only square-cornered element left in a row that otherwise sits beside `rounded-md` cards,
 *   and `text-text/75` is an opacity fake of a grey we have a real token for.
 */
import { Icon } from './Icon';
import { parseCitations, type Citation } from '@/lib/citations';

export interface CitationChipProps {
  citation: Citation;
  className?: string;
}

export function CitationChip({ citation, className = '' }: CitationChipProps) {
  return (
    <a
      href={citation.url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      title={citation.quote ? `“${citation.quote}”` : citation.url}
      data-citation="true"
      className={`inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-0.5 font-mono text-caption leading-normal text-muted transition-colors duration-[120ms] hover:border-border-strong hover:text-text ${className}`}
    >
      <Icon name="arrowRight" size={10} className="-rotate-45 shrink-0" aria-hidden="true" />
      <span className="truncate">{citation.host}</span>
    </a>
  );
}

export interface CitationListProps {
  citations: Citation[];
  className?: string;
}

/** A row of chips. Renders nothing at all when there is nothing to cite. */
export function CitationList({ citations, className = '' }: CitationListProps) {
  if (citations.length === 0) return null;
  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${className}`}>
      {citations.map((c) => (
        <CitationChip key={c.url} citation={c} />
      ))}
    </div>
  );
}

export interface SourcedLineProps {
  /** Raw prose from the API, citation scaffolding included. */
  children: string;
  className?: string;
  chipClassName?: string;
}

/**
 * A line of sourced prose: the claim, then the sources it stands on.
 *
 * Safe to point at any string. A line with no URL renders exactly as it did before this
 * component existed -- same text, no chip row, no wrapper cost -- so it can be applied to
 * fields that only *sometimes* carry a citation without auditing each one first.
 */
export function SourcedLine({ children, className = '', chipClassName = '' }: SourcedLineProps) {
  const { text, citations } = parseCitations(children);
  return (
    <>
      <span className={className}>{text}</span>
      <CitationList citations={citations} className={`mt-2 ${chipClassName}`} />
    </>
  );
}
