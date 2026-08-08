import React from 'react';
import { Glyph, SourcedLine } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { parseCitations } from '@/lib/citations';
import type { PackDetails } from '@/lib/api/client';

/**
 * The first thing on the money page: a real page of the pack's own evidence record.
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
 * The claim under test on this page is "this record exists and is sourced". A cover cannot
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
export default function EvidenceExcerptPlate({
  pack,
  className,
}: {
  pack: PackDetails;
  /* The plate used to open the page, so its spacing was a hardcoded `mb-8` and its position was
     not the caller's business. It now sits under the header block on the pack page, so the
     caller owns the gap above it. */
  className?: string;
}) {
  // Plain, not `React.useMemo`. The compiler refused to preserve the memo here ("Existing
  // memoization could not be preserved", eslint react-hooks/preserve-manual-memoization) because
  // of the early return inside the loop, which meant the file failed lint AND lost every other
  // optimisation the compiler would have applied to this component. The work is one pass over at
  // most a handful of lines; the compiler memoizes it for us.
  const first = firstCitedLine(pack.sampleExtract);
  const reference = recordReference(pack.dossierRef);

  if (!first) return null;

  return (
    <figure className={cx('overflow-hidden rounded-md border border-border bg-surface', className)}>
      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border bg-surface2 px-5 py-3">
        <span className="inline-flex items-center gap-2 text-caption font-medium text-muted">
          <Glyph name="source" className="text-success" />
          One page of the evidence record
        </span>
        {/* The reference only. Mono because it is the one value on this plate a reader would
            transcribe or quote back to us; prose stays in the sans (`monoIsTheDataVoice`).
            The source COUNT used to sit here too, and desktop-pack-fold.png (2026-08-06) showed
            why that was wrong: `33 sources` printed here and again ~200px below in the evidence
            row under the sub-copy, so the fold of the money page spent two lines saying one
            number. The count is a fact about the PACK and belongs in the pack's evidence row;
            this plate identifies the RECORD the excerpt was lifted from (`dossierRef` is the
            API's own field name, and renaming a wire field is a different, breaking change). */}
        {reference && (
          <span className="font-mono text-caption text-subtle">{reference}</span>
        )}
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

/**
 * The record reference as a buyer may read it: the id, without the wire field's type prefix.
 *
 * WHY THIS EXISTS. `dossierRef` arrives from the API as `dossier:8d5a441749448b69` and was
 * rendered verbatim, so every pack page printed the word "dossier" -- retired by SITE_SPEC 5.2 in
 * favour of "pack", with "evidence record" as the name for the record inside one. Confirmed live
 * on 2026-08-08: `curl https://mumchimp.com/pack/8d5a441749448b69` returns `dossier:8d5a44...`.
 *
 * WHY THE PROBE SAID THIS WAS CLEAN. `site_spec_probe.py` reads 5.2 out of PROSE -- JSX text and
 * sentence-shaped literals -- and this string is neither: it is an interpolation whose value is
 * assembled by the API at runtime. No amount of source scanning can see it, which is why the
 * probe printed "0 reader-facing instances of catalog/shot/grounded/gauntlet/dossier" over a term
 * that was on every pack page. A source-only vocabulary check is blind to any retired word that
 * arrives over the wire, and this is the first one that did.
 *
 * The FIELD keeps its name. Renaming a wire field is a breaking change and is not the defect; the
 * defect is showing a reader a type tag from our own schema. Stripping is done here, at the render
 * boundary, so a republish cannot reintroduce it.
 *
 * The prefix is stripped by SHAPE (`word:` at the start), not by matching "dossier", so an API
 * that renames the field's prefix tomorrow does not start leaking again. Returns null for an
 * absent or prefix-only value: `store/listings/*.json` carries `dossierRef: null` on live rows
 * while `client.ts:144` types it a required `string`, so the empty case is reachable today.
 */
export function recordReference(ref: string | null | undefined): string | null {
  const id = (ref ?? '').trim().replace(/^[a-z][a-z0-9_]*:/i, '').trim();
  return id === '' ? null : id;
}

/** The first extract line that actually resolves a citation, or null when none does. */
function firstCitedLine(lines: string[] | null | undefined) {
  for (const line of lines ?? []) {
    const parsed = parseCitations(line);
    if (parsed.citations.length > 0) return { line, citations: parsed.citations };
  }
  return null;
}
