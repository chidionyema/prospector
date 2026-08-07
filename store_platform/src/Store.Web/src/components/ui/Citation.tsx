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
import { SourceChip, SourceChipRow } from './SourceChip';
import { parseCitations, type Citation } from '@/lib/citations';

export interface CitationChipProps {
  citation: Citation;
  className?: string;
}

/**
 * A citation, drawn as the sitewide source chip.
 *
 * The markup moved to `SourceChip` (2026-08-07) when it turned out four other surfaces had each
 * grown their own copy of it. This stays as the name the citation-parsing code calls it by --
 * `Citation` is a parsed thing with a `host` and a `quote`, `SourceChip` is a way of drawing a
 * link -- but there is now exactly one implementation underneath.
 */
export function CitationChip({ citation, className = '' }: CitationChipProps) {
  return (
    <SourceChip
      url={citation.url}
      host={citation.host}
      quote={citation.quote}
      className={className}
    />
  );
}

export interface CitationListProps {
  citations: Citation[];
  className?: string;
}

/** A row of chips. Renders nothing at all when there is nothing to cite. */
export function CitationList({ citations, className = '' }: CitationListProps) {
  return <SourceChipRow sources={citations} className={className} />;
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
