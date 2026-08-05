import React from 'react';
import Link from 'next/link';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { categoryFor } from '@/lib/category';
import type { Pack } from '@/lib/api/client';

export interface PackCoverProps {
  pack: Pack;
  /**
   * `square` is the 1:1 cover on the pack card (and the trending row).
   * `hero` is the 16:9 cover on the pack detail page.
   *
   * The cover is a real design plate: the pack's name as the primary type,
   * a sector monogram as the visual anchor, the dossier ID as a quiet
   * authenticity signal, and the category tint carrying the colour story.
   * No coloured rectangles. The old gradient-with-faint-icon template was
   * the single biggest tell that the page was unfinished.
   */
  variant: 'square' | 'hero';
  /**
   * When true, the cover is a `<Link>` to the pack's detail page. The card
   * surfaces use this so the cover is independently clickable; the detail
   * page's hero is a passive banner and does not.
   */
  asLink?: boolean;
  /** Optional className passthrough for layout (margin, padding). */
  className?: string;
}

/**
 * The cover plate for a pack: typography + a sector monogram + dossier ID, sized
 * 1:1 (square) or 16:9 (hero). One component, used by every pack card on the
 * home page and the pack detail page.
 *
 * The cover has to do four jobs at once:
 *   1. Make a 60-pack shelf scannable from across the room (so the sector
 *      monogram and the colour tint carry the visual story).
 *   2. Identify the pack without reading the title (so the pack ID, top-left,
 *      reads as the dossier number, the same affordance a real research
 *      report uses).
 *   3. Earn the title (so the pack title itself is the dominant type).
 *   4. Stay cheap to render (no real imagery, no fetch, no CLS).
 *
 * The category gradient alone, the previous design, failed jobs 1 and 2 and
 * silently failed 3, because every pack in a sector looked identical. Now
 * every pack reads as its own document, in the same colour family as its
 * sector, the way a properly designed series looks.
 */
export default function PackCover({ pack, variant, asLink = false, className }: PackCoverProps) {
  const cat = categoryFor(pack);
  const aspectClass = variant === 'square' ? 'aspect-square' : 'aspect-[16/9]';

  // The cover carries the pack's own identity, not the sector's. The sector
  // supplies the palette and the monogram; the pack supplies the title, the
  // ID, and the one-line subtitle (if any).
  /*
   * The untagged fallback was `bg-text`, a flat #0A0A0A slab. On the pack detail page that renders
   * as a ~550px tall near-black rectangle above the title, and the three overlays below it are all
   * white-on-transparent or black-on-transparent, so none of them show up against it. It does not
   * read as a designed cover, it reads as an image that failed to load, on the money page, at the
   * top of the fold. It is not a rare edge case either: a large share of the live catalogue
   * carries no facets at all, so this is the default cover for many packs.
   *
   * Replaced with a deep slate gradient in the same family as the tagged covers, so an untagged
   * pack looks like the neutral member of the series rather than an error state. The vignettes
   * and the grain now have something to sit on.
   */
  const palette = cat.tagged
    ? cat.cover
    : 'bg-[linear-gradient(135deg,#1F2937_0%,#0F172A_100%)]';
  const monogram = cat.tagged ? cat.icon : 'briefcase';

  const content = (
    <div
      className={cx(
        'relative overflow-hidden border border-border isolate',
        aspectClass,
        palette,
        className,
      )}
    >
      {/* Paper grain. The same texture the brand chrome uses, scaled up so
          a cover at full width still feels printed, not flat-painted. */}
      <div className="pointer-events-none absolute inset-0 mix-blend-overlay opacity-30 bg-[radial-gradient(rgba(255,255,255,0.6)_1px,transparent_1px)] [background-size:3px_3px]" />
      {/* Top-left vignette: a single source-of-light from the upper-left, so
          the type below it sits on a non-flat background. Matches the rest
          of the site's lighting. */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_120%_at_10%_-10%,rgba(255,255,255,0.35),transparent_55%)]" />
      {/* Bottom-right: a soft fade so the sector monogram doesn't crash into
          the edge. */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(80%_80%_at_100%_100%,rgba(0,0,0,0.35),transparent_50%)]" />

      {/* Dossier number, top-left: the pack's own ID. Reads as the report
          reference (like an ISBN or a regulatory citation), gives the cover
          the feel of a real research document. Truncated if it's long. */}
      <div className="absolute left-3 top-3 right-3 flex items-start justify-between gap-2 font-mono text-[9px] font-bold uppercase tracking-[0.2em] text-white/85">
        <span className="truncate">№ {pack.id.slice(0, 12)}</span>
        <span className="shrink-0 rounded-sm bg-black/20 px-1.5 py-0.5 backdrop-blur-sm">
          {pack.market?.toUpperCase() ?? 'UK'}
        </span>
      </div>

      {/* Sector monogram, bottom-right: the only large graphic. The icon
          carries meaning (a buyer who knows the catalogue recognises the
          monogram at a distance), and its scale is what tells the eye
          "this is a designed cover, not a placeholder rectangle". */}
      <Icon
        name={monogram}
        size={variant === 'square' ? 110 : 180}
        className="pointer-events-none absolute -bottom-6 -right-6 text-white/20 transition-transform duration-500 group-hover:scale-110 group-hover:-rotate-3"
      />

      {/* Pack title + one-line, bottom-left. The dominant type. Sits on a
          subtle ink-tinted panel so the title reads against any sector
          colour. The clamp lines keep every cover to a consistent height,
          which is the only way a 60-pack grid stays calm. */}
      <div className="absolute inset-x-0 bottom-0 px-4 pb-4 pt-12 bg-gradient-to-t from-black/55 via-black/25 to-transparent">
        <p className="font-serif text-[15px] font-bold leading-[1.15] text-white line-clamp-3">
          {pack.title}
        </p>
        {pack.cardLine && variant === 'hero' && (
          <p className="mt-2 text-[11px] leading-snug text-white/85 line-clamp-2 font-medium">
            {pack.cardLine}
          </p>
        )}
        {/* Sector label, micro. Lives under the title on hero covers only;
          on square cards the sector is already implied by the monogram,
          and adding the text would crowd the cover. */}
        {cat.tagged && variant === 'hero' && (
          <p className="mt-2 font-mono text-[9px] font-bold uppercase tracking-[0.2em] text-white/75">
            {cat.label}
          </p>
        )}
      </div>
    </div>
  );

  if (asLink) {
    return (
      <Link href={`/pack/${pack.id}`} aria-label={pack.cardLine || pack.title}>
        {content}
      </Link>
    );
  }
  return content;
}
