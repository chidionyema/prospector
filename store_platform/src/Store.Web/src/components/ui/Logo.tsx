import React from 'react';
import { cx } from './cx';
import { BRAND } from '@/lib/config';

interface LogoProps {
  className?: string;
  /**
   * Flip the lockup for the dark `band` / footer (the colour lock, the contrast rule): the tile goes
   * WHITE with a deep-blue "IX", and the wordmark inverts to light. On light backgrounds (default) the
   * tile is the DEEP BLUE `--band` (the logo and the band are the SAME shade — one blue family) with a
   * white "IX". Deep blue is the constant hue across both states; only the tile/mark lightness flips.
   * The mark always differs from its ground in both hue and lightness (deep-blue tile 9.84:1 vs page
   * bg, white IX 10.36:1 on deep blue, deep-blue IX 10.36:1 on the white footer tile — all AAA, far
   * over the 3:1 WCAG non-text floor).
   */
  onDark?: boolean;
  /** Only render the 'IX' tile monogram, omitting the wordmark (requested for sticky header polish). */
  monogramOnly?: boolean;
}

/**
 * Brand lockup: an "IX" monogram + the configurable wordmark (BRAND.name).
 *
 * Supersedes the WR-021/WR-022 "IE" lettermark, which in practice read as a plain "E" with a stray
 * gold dash (founder + external design review, 2026-06-06). The replacement is a real monogram:
 * "IX" = Introduction eXchange, set on the DEEP-BLUE tile (the same `--band` deep blue as the dark
 * section/footer — one blue family, the colour lock), with the X drawn as two crossing strokes (one
 * full, one at reduced opacity) so it reads as two forms meeting, the "exchange". The logo shares the
 * band's deep blue; bright blue is reserved for buttons ("click"). NO gold: the founder rule is gold =
 * settled-money signals only (WR-033), so brand chrome carries none. Depth comes from the two-tone X.
 *
 * The wordmark renders from the single configurable `BRAND.name` (lib/config) so the name matches
 * the page title, OG/Twitter meta, both footers, and email everywhere at once — change it in one
 * place. We split on the first space to set the leading article muted and the rest emphasised; a
 * single-word name renders wholly emphasised. The visible wordmark hides below `sm` so a phone header
 * stays uncrowded; the SVG is aria-hidden and the accessible name is carried by each header link's
 * aria-label.
 *
 * One weight pair only (400 / 600). Source of truth for the favicon/app icon too: public/icon.svg is
 * regenerated from this monogram.
 */
export function Logo({ className, onDark = false, monogramOnly = false }: LogoProps) {
  const color = onDark ? 'text-white' : 'text-text';
  
  const monogram = (
    <svg viewBox="0 0 100 60" className={cx('h-9 w-15 flex-none overflow-visible', className)} aria-hidden="true">
      <defs>
        {/* Elite Institutional Gradients */}
        <linearGradient id="midnight-base" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={onDark ? "var(--bg)" : "var(--brand-midnight-0)"} />
          <stop offset="1" stopColor={onDark ? "var(--border)" : "var(--brand-midnight-100)"} />
        </linearGradient>
        
        <linearGradient id="sapphire-kinetic" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="var(--brand-sapphire-0)" />
          <stop offset="0.6" stopColor="var(--brand-sapphire-40)" />
          <stop offset="1" stopColor="var(--brand-sapphire-100)" />
        </linearGradient>

        {/* 
          PRECISION WEAVE MASK (The Optical Illusion)
          Instead of fuzzy shadows, we use a 1.5px negative space cutout where paths intersect.
          This signals institutional precision and high-fidelity vector execution.
        */}
        <mask id="monogram-mask">
          <rect x="0" y="0" width="100" height="60" fill="white" />
          
          {/* 1. THE KEYHOLE HOOK (Unlock Doors) 
              A subtle keyhole silhouette cut from the center of the 'I' pillar.
          */}
          <circle cx="27.5" cy="30" r="4.5" fill="black" />
          <path d="M 26,32 L 29,32 L 31,42 L 24,42 Z" fill="black" />

          {/* 2. THE WEAVE GAPS
              We cut a wider path (strokeWidth + 3px) from the background layers 
              where the top sapphire stroke crosses over.
          */}
          <path d="M 38,12 L 68,48" stroke="black" strokeWidth="11" strokeLinecap="round" fill="none" />
        </mask>
      </defs>

      <g transform="translate(0, 0)">
        {/* BACKGROUND GROUP: Masked to create the Keyhole and the Weave Gaps */}
        <g mask="url(#monogram-mask)">
          {/* THE "I" STEM: The grounded, structural pillar */}
          <rect x="23.5" y="10" width="8" height="40" rx="1.5" fill="url(#midnight-base)" />

          {/* THE "X" BACK-SLASH: Curved Asymmetry (Breaking the SaaS template)
              Uses a sweeping curve to contrast with the sharp forward slash.
          */}
          <path d="M 72,12 C 60,18 45,40 38,50" 
                stroke="url(#midnight-base)" strokeWidth="7" strokeLinecap="round" fill="none" />
        </g>

        {/* THE "X" FORWARD-SLASH: The Kinetic Key
            A sharp, straight vector representing the "Key" that unlocks the introduction.
            This sits on top of the weave.
        */}
        <path d="M 38,12 L 68,48" 
              stroke="url(#sapphire-kinetic)" strokeWidth="8" strokeLinecap="round" fill="none" />
              
        {/* OPTICAL HIGHLIGHT: A 0.5px ultra-thin light reflection line */}
        <path d="M 38.5,12.5 L 67.5,47.5" 
              stroke="var(--brand-reflection)" strokeWidth="0.5" strokeLinecap="round" strokeOpacity="0.3" fill="none" />
      </g>
    </svg>
  );

  if (monogramOnly) {
    return monogram;
  }

  const [article, ...rest] = BRAND.name.split(' ');
  const emphasised = rest.join(' ');

  return (
    <div className={cx('flex items-center gap-2', className)}>
      {monogram}
      <span className="sr-only">{BRAND.name}</span>
      <div className="flex flex-col -space-y-1" aria-hidden="true">
        {emphasised ? (
          <>
            <span className={cx('whitespace-nowrap font-sans text-lg font-bold tracking-tighter leading-tight uppercase opacity-50', color)}>
              {article}
            </span>
            <span className={cx('whitespace-nowrap font-sans text-2xl font-bold tracking-tighter leading-none', color)} style={{ clipPath: 'polygon(0% 0%, 100% 2%, 100% 100%, 0% 98%)' }}>
              {emphasised}
            </span>
          </>
        ) : (
          <span className={cx('whitespace-nowrap font-sans text-2xl font-bold tracking-tighter leading-none', color)}>
            {article}
          </span>
        )}
      </div>
    </div>
  );
}
