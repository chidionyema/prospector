import React from 'react';
import { Icon, SourcedLine, CitationList } from '@/components/ui';
import { parseCitations } from '@/lib/citations';
import type { PackDetails } from '@/lib/api/client';

/**
 * The first thing on the money page: a real page of the pack's own dossier.
 *
 * WHAT THIS REPLACED
 *
 * `<PackCover variant="hero" />` -- a ~550px 16:9 plate carrying a gradient, a sector monogram,
 * the pack ID, a market tag and the title again. Measured 2026-08-05 it occupied the whole fold
 * above the `h1` and told the buyer nothing they did not already have from the tab title and the
 * breadcrumb. On a page whose entire pitch is "every claim has a source you can open", the prime
 * visual slot was spending itself on decoration.
 *
 * WHY AN EXCERPT AND NOT A NICER COVER
 *
 * The claim under test on this page is "this dossier exists and is sourced". A cover cannot
 * carry that claim -- a pack with nothing behind it renders an identical cover, which is exactly
 * what makes it worthless as evidence. A line lifted from `sampleExtract` with its source
 * resolved to a live anchor cannot be rendered by an empty pack: no extract, no plate.
 *
 * That is the deliberate degradation rule. When `sampleExtract` is absent or carries no citation,
 * this component renders NOTHING, and the page opens on the title. An empty rectangle is not a
 * neutral fallback here; it is the failure mode being removed.
 *
 * The same lines are shown in full further down ("A look inside"). The repetition is intended:
 * this is the pull-quote, that is the section. What must never diverge is the source -- both
 * render through `parseCitations`, so a line's anchor is the same anchor in both places.
 */
export default function DossierExcerptPlate({ pack }: { pack: PackDetails }) {
  const first = React.useMemo(() => {
    for (const line of pack.sampleExtract ?? []) {
      const parsed = parseCitations(line);
      if (parsed.citations.length > 0) return { line, citations: parsed.citations };
    }
    return null;
  }, [pack.sampleExtract]);

  if (!first) return null;

  return (
    <figure className="mb-8 border border-border bg-surface">
      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border bg-bg/60 px-5 py-3">
        <span className="inline-flex items-center gap-2 text-caption font-bold uppercase tracking-widest text-muted">
          <Icon name="verified" size={13} className="text-success" />
          One page of the verification dossier
        </span>
        {/* Mono, because these are the two values on the plate a reader would transcribe or
            compare: the audit reference and a count. Prose stays in the sans (`monoIsTheDataVoice`). */}
        <span className="font-mono text-caption text-muted">
          {pack.dossierRef}
          {typeof pack.sourceCount === 'number' && pack.sourceCount > 0
            ? ` · ${pack.sourceCount} sources`
            : ''}
        </span>
      </figcaption>

      <blockquote className="border-l-2 border-l-success px-5 py-5 md:px-7">
        <SourcedLine className="block max-w-[68ch] text-body leading-relaxed text-text/85">
          {first.line}
        </SourcedLine>
        {/* Rendered again as chips, not only inline: inline anchors prove the source exists,
            chips make the domain legible without hovering, which is the thing a sceptical buyer
            is actually checking at this point on the page. */}
        <CitationList citations={first.citations} className="mt-3" />
      </blockquote>
    </figure>
  );
}
