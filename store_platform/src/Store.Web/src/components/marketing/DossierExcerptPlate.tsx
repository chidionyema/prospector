import React from 'react';
import { Icon, SourcedLine } from '@/components/ui';
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
  // Plain, not `React.useMemo`. The compiler refused to preserve the memo here ("Existing
  // memoization could not be preserved", eslint react-hooks/preserve-manual-memoization) because
  // of the early return inside the loop, which meant the file failed lint AND lost every other
  // optimisation the compiler would have applied to this component. The work is one pass over at
  // most a handful of lines; the compiler memoizes it for us.
  const first = firstCitedLine(pack.sampleExtract);

  if (!first) return null;

  return (
    <figure className="mb-8 overflow-hidden rounded-md border border-border bg-surface">
      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border bg-surface2 px-5 py-3">
        <span className="inline-flex items-center gap-2 text-caption font-medium text-muted">
          <Icon name="verified" size={13} className="text-success" />
          One page of the verification dossier
        </span>
        {/* The reference only. Mono because it is the one value on this plate a reader would
            transcribe or quote back to us; prose stays in the sans (`monoIsTheDataVoice`).
            The source COUNT used to sit here too, and desktop-pack-fold.png (2026-08-06) showed
            why that was wrong: `33 sources` printed here and again ~200px below in the evidence
            row under the sub-copy, so the fold of the money page spent two lines saying one
            number. The count is a fact about the PACK and belongs in the pack's evidence row;
            this plate identifies the DOSSIER the excerpt was lifted from. */}
        <span className="font-mono text-caption text-subtle">{pack.dossierRef}</span>
      </figcaption>

      <blockquote className="border-l-2 border-l-success px-5 py-5 md:px-7">
        {/* `SourcedLine` already strips the `(source: ...)` scaffolding into a chip row of its
            own -- see ui/Citation.tsx:90. This used to render `<CitationList>` again underneath
            it on the same `first.citations`, which put two identical `legalclarity.org` chips in
            the fold of the money page (caught in desktop-pack-fold.png, 2026-08-06). One claim,
            one source row. */}
        <SourcedLine className="block max-w-[68ch] text-body text-text">{first.line}</SourcedLine>
      </blockquote>
    </figure>
  );
}

/** The first extract line that actually resolves a citation, or null when none does. */
function firstCitedLine(lines: string[] | null | undefined) {
  for (const line of lines ?? []) {
    const parsed = parseCitations(line);
    if (parsed.citations.length > 0) return { line, citations: parsed.citations };
  }
  return null;
}
