import React from 'react';
import Link from 'next/link';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { categoryFor, type Category } from '@/lib/category';
import type { Pack } from '@/lib/api/client';

export interface PackCoverProps {
  pack: Pack;
  /**
   * `square` is the 1:1 cover on the pack card (and the trending row).
   * `hero` is the 16:9 cover on the pack detail page.
   * The visual is the same in both variants: a category-coloured gradient with a
   * faint category icon. The aspect ratio is what changes; the cover scales
   * gracefully either way.
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
 * The cover plate for a pack: a category-coloured gradient with a faint category
 * icon, sized 1:1 (square) or 16:9 (hero). One component, used by every pack
 * card on the home page and the pack detail page.
 *
 * US-2 (audit §4.2): the catalogue was 45 identical left-rule documents, with
 * no way to tell a "story book for autistic kids" from a "shower drain
 * unblocker" without reading the title. The cover makes every pack visually
 * distinct from across the room, while staying cheap to render (no real
 * imagery, no fetch, no CLS).
 *
 * Out of scope (per the spec): generating 60 unique covers. The cover derives
 * from the pack's category, so every pack in a given category shares the same
 * colour and icon. The "five art plates per category" was a future polish
 * target; the category gradient is the pragmatic default until bespoke art
 * lands.
 *
 * Untagged packs (no category) get a neutral warm-tan fallback so the cover
 * is never blank. The audit called this out specifically: "A pack with no
 * category renders nothing" is the wrong default.
 */
export default function PackCover({ pack, variant, asLink = false, className }: PackCoverProps) {
  const cat = categoryFor(pack);
  // The aspect ratio is what makes the visual work - the gradient and the
  // icon are the same in both variants, the rectangle they sit inside is
  // not.
  const aspectClass = variant === 'square' ? 'aspect-square' : 'aspect-[16/9]';
  // The icon size scales with the variant: square covers are smaller, hero
  // covers carry more weight.
  const iconSize = variant === 'square' ? 48 : 96;
  // The fallback colour is the warm-tan border so untagged packs blend
  // with the rest of the page rather than disappearing.
  const tone = cat.tagged ? cat.cover : 'bg-surface2';

  const content = (
    <div
      className={cx(
        'relative overflow-hidden border border-border',
        aspectClass,
        tone,
        className,
      )}
    >
      {/* Soft top highlight, the same trick the rest of the site uses. The
          radial-gradient is on the cover itself so the badge text and the
          icon both sit on a non-flat background. */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_120%_at_12%_-10%,rgba(255,255,255,0.25),transparent_55%)]" />
      {/* Faint category icon at the bottom-right. 15% opacity, scale-up on
          hover, the same animation the existing spotlight cover uses. The
          icon is the only thing on the cover that carries semantic meaning;
          a buyer who knows the icon catalogue can scan a row of packs at
          a glance. */}
      {cat.tagged && (
        <Icon
          name={cat.icon}
          size={iconSize}
          className="pointer-events-none absolute -bottom-6 -right-4 text-white/15 transition-transform duration-300 group-hover:scale-105"
        />
      )}
      {/* Untagged packs: a generic pack glyph at low opacity. The fallback
          must still look like a pack, not a blank rectangle. */}
      {!cat.tagged && (
        <Icon
          name="briefcase"
          size={iconSize}
          className="pointer-events-none absolute -bottom-6 -right-4 text-text/15 transition-transform duration-300 group-hover:scale-105"
        />
      )}
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
