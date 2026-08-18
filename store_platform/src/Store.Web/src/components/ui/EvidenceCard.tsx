import React from 'react';
import { SourceChip } from './SourceChip';
import { cx } from './cx';

/**
 * A quote, and the page it came from, as one object (MASTER-BRIEF §6).
 *
 * The brief calls this "the most reusable component in the system -- it is what 'every claim is
 * sourced' looks like when shown rather than said". The shop's whole pitch is that a claim arrives
 * with the page behind it, and until now the site had no way to render that pairing generically:
 * `EvidenceExcerptPlate` does it beautifully and takes a `PackDetails`, so it can only ever appear
 * on a pack page. Every other surface that wanted a sourced quote hand-rolled a blockquote and a
 * link, which is how two of them ended up with an anchor that opened nothing.
 *
 * THE SOURCE IS NOT OPTIONAL. There is no unsourced variant and there must not be one: a quote
 * without its page is the thing this component exists to make impossible to draw by accident.
 *
 * The teal left rule and the tint ground are §6's, and they are load-bearing rather than
 * decorative -- teal is the brand's evidence colour everywhere on the site, so a reader who has
 * seen one of these recognises the next without reading it. `--brand` on `--brand-tint` measures
 * 5.50:1, and the quote itself is `--ink` on the tint, which is far past AA.
 */

export interface EvidenceCardProps {
  /** The claim, in the source's own words. Rendered as a quotation, not as prose. */
  quote: React.ReactNode;
  /** The page it came from. Opens in a new tab, `noopener`, like every source link here. */
  href: string;
  /**
   * The host as a reader should see it. Omit and `SourceChip` derives it from `href` -- pass it
   * only when the corpus already carries a cleaned domain.
   */
  sourceDomain?: string;
  /** Optional line above the quote: what this evidence is FOR. */
  caption?: React.ReactNode;
  className?: string;
}

export function EvidenceCard({
  quote,
  href,
  sourceDomain,
  caption,
  className,
}: EvidenceCardProps) {
  return (
    <figure
      className={cx(
        'rounded-card border border-line border-l-2 border-l-brand bg-brand-tint px-5 py-4',
        className,
      )}
    >
      {caption && (
        <figcaption className="mb-2 text-caption font-medium text-muted">{caption}</figcaption>
      )}
      <blockquote className="max-w-[68ch] text-body leading-relaxed text-text">{quote}</blockquote>
      <div className="mt-3">
        <SourceChip url={href} host={sourceDomain} variant="link" />
      </div>
    </figure>
  );
}

export default EvidenceCard;
