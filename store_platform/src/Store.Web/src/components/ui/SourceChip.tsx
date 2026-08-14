/**
 * The one way this site draws "a source you can open".
 *
 * `SITE_SPEC_PROGRAM.md` §4 calls the source chip a *sitewide primitive* -- "any sourced claim gets
 * one" -- and until this file existed there were **five** implementations of it in two different
 * visual languages:
 *
 *   ui/Citation.tsx `CitationChip`      bordered chip, arrow glyph, mono host, muted
 *   pages/sample.tsx `SourceChips`      bordered chip, arrow glyph, mono host, larger padding
 *   components/marketing/HeroEvidenceStrip    bare mono link, underline decoration-border
 *   components/marketing/CheckSequence       bare mono link, underline decoration-border
 *   components/marketing/EvidenceRecordPanel bare mono link via `textLinkClass`, accent-coloured
 *
 * The tell that this was drift rather than design: `HeroEvidenceStrip.tsx` carried a comment reading
 * "the -45deg arrow copy `SourceChips` on `/sample` deliberately: this site has one way of drawing
 * 'a source you can open'" -- above markup with no arrow, no border and a different colour. A
 * comment asserting consistency is not consistency, and nothing in the tree could tell the
 * difference, because no test named the chip. Five copies is what an unguarded primitive becomes.
 *
 * WHY TWO VARIANTS AND NOT ONE. §4 asks for a single form. Collapsing `link` into `chip` is a
 * visible change to the hero and to `/how-it-works`, which is a founder call, not a refactor -- so
 * both forms survive here as *declared* variants with one implementation behind them. That is the
 * part that was actually broken: not that the hero draws sources compactly, but that it drew them
 * with its own private copy of the markup. See `sourceChipIsTheOnlyOne.test.ts`, which forbids a
 * sixth.
 *
 * `rel` is unified to include `nofollow`. Two of the five omitted it. `CitationChip`'s reasoning
 * applies to all of them and always did: these are cited sources, not endorsements, and some packs
 * carry 51 of them.
 */
import { Icon } from './Icon';
import { textLinkClass } from './TextLink';

/**
 * The hostname a reader uses to judge provenance -- `assets.publishing.service.gov.uk` vs
 * someone's blog -- with `www.` dropped.
 *
 * Replaces three private `domainOf` helpers (`HeroEvidenceStrip.tsx:31`, `EvidenceRecordPanel.tsx:25`,
 * `CheckSequence.tsx:48`) that differed in what they did with a malformed URL. Returns `''` rather than
 * throwing, because a bad URL in engine output must not blank a whole page; callers that render
 * the host will simply render nothing.
 */
export function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

export type SourceChipVariant = 'chip' | 'link';

export interface SourceChipProps {
  /** Absolute URL, exactly as it appeared in the prose. */
  url: string;
  /** Visible label. Defaults to the URL's hostname. */
  host?: string;
  /** Optional one-liner on what this source evidences. Rendered by the `chip` variant only. */
  label?: string;
  /** The passage the claim is grounded in, shown as the native tooltip. */
  quote?: string;
  /**
   * `chip` -- bordered, for a row of receipts under a claim. The default, and the form §4
   * describes.
   * `link` -- bare mono underline, for a dense inline strip of domains where a border per source
   * would read as a toolbar rather than as evidence.
   */
  variant?: SourceChipVariant;
  className?: string;
}

export function SourceChip({
  url,
  host,
  label,
  quote,
  variant = 'chip',
  className = '',
}: SourceChipProps) {
  const text = host ?? sourceHost(url);
  const common = {
    href: url,
    target: '_blank',
    rel: 'noopener noreferrer nofollow',
    title: quote ? `“${quote}”` : url,
    'data-source-chip': variant,
  } as const;

  if (variant === 'link') {
    return (
      <a
        {...common}
        className={textLinkClass(`font-mono text-caption duration-[120ms] ${className}`)}
      >
        {text}
      </a>
    );
  }

  return (
    <a
      {...common}
      // No favicon, deliberately. The obvious implementation fetches
      // `google.com/s2/favicons?domain=` per source, which sends every visitor's IP to Google on
      // every pack page -- on a storefront with a no-device-storage analytics branch. A link glyph
      // plus the hostname carries the same "this is a real place on the web" signal with no
      // third-party request.
      className={`inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-0.5 font-mono text-caption leading-normal text-muted transition-colors duration-[120ms] hover:border-border-strong hover:text-text ${className}`}
    >
      <Icon name="arrowRight" size={10} className="-rotate-45 shrink-0" aria-hidden="true" />
      <span className="truncate">{text}</span>
      {label && <span className="truncate font-sans text-muted">{label}</span>}
    </a>
  );
}

export interface SourceChipRowProps {
  sources: { url: string; host?: string; label?: string; quote?: string }[];
  variant?: SourceChipVariant;
  className?: string;
  chipClassName?: string;
}

/** A row of sources. Renders nothing at all when there is nothing to cite. */
export function SourceChipRow({
  sources,
  variant = 'chip',
  className = '',
  chipClassName = '',
}: SourceChipRowProps) {
  if (sources.length === 0) return null;
  return (
    <div
      className={`flex flex-wrap items-center ${variant === 'link' ? 'gap-x-3 gap-y-1.5' : 'gap-1.5'} ${className}`}
    >
      {sources.map((s) => (
        <SourceChip key={s.url} {...s} variant={variant} className={chipClassName} />
      ))}
    </div>
  );
}
