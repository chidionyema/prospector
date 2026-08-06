import React from 'react';
import Link from 'next/link';
import { Button, Card, Icon, cx } from '@/components/ui';
import type { IconName, ButtonVariant } from '@/components/ui';

/**
 * Small presentational blocks shared across the WR-014 GTM marketing pages.
 * Semantic tokens only (raw hex/palette fails `npm run conformance`). No data, no API, these
 * are pure layout/typography so the pages stay static and Pact-free.
 */

/**
 * Full-bleed section background with the standard inner content container.
 *
 * Brand v3 (2026-08-06): `band` is GONE. It painted whole sections near-black, which is what
 * forced the `inverse`/`inverseGhost` buttons, the `--on-band*` text tokens and a second set of
 * contrast rules for every component that could land inside one. Two colour systems in one page
 * is how the site ended up with black-on-orange CTAs. Section separation now comes from
 * `--surface2` (#FAFAFA) and the hairline bottom border, nothing else.
 *
 * `band` and `vault-wash` are kept in the map as aliases so the ~20 call sites do not all have to
 * change in the same commit; both resolve to the off-white wash.
 */
type BandBg = 'surface' | 'surface2' | 'band' | 'vault-wash' | 'white' | 'bg';
const BAND_BG: Record<BandBg, string> = {
  surface: 'bg-surface',
  surface2: 'bg-surface2',
  band: 'bg-surface2',
  'vault-wash': 'bg-surface2',
  white: 'bg-surface',
  bg: 'bg-bg',
};
const BAND_WIDTH = { '2xl': 'max-w-2xl', '3xl': 'max-w-3xl', '4xl': 'max-w-4xl', '6xl': 'max-w-6xl', '7xl': 'max-w-7xl' } as const;

export function SectionBand({
  bg = 'surface',
  width = '3xl',
  className,
  children,
}: {
  bg?: BandBg;
  width?: keyof typeof BAND_WIDTH;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cx(BAND_BG[bg], "border-b border-border last:border-b-0")}>
      <div className={`mx-auto ${BAND_WIDTH[width]} overflow-hidden px-6 md:px-8 lg:px-10 ${className ?? ''}`}>
        {children}
      </div>
    </section>
  );
}

/**
 * A page hero: label, headline, lead, up to two actions. Left-aligned and tight.
 *
 * Three things were removed and each was doing visible damage:
 *  - `md:min-h-[calc(100dvh-4rem)]` forced every marketing hero to fill the viewport, which is
 *    what pushed the content of every page below the fold on a laptop.
 *  - `text-center` centred prose up to 50ch wide; a centred ragged-both-edges paragraph is
 *    measurably slower to read because each line starts at a different x.
 *  - `uppercase tracking-wide font-bold` on the buttons: three loudness devices on one control.
 */
export function PageHero({
  bg = 'white',
  /**
   * The band width, which must be the width the REST of the page uses.
   *
   * It was hardcoded to '4xl' and four of the five pages that render a hero set their body bands
   * to 6xl or 7xl, so those pages had two left edges: on /how-it-works the headline and lead began
   * at x=432 and every one of the six checks below began at x=258 (desktop-how-it-works-fold.png,
   * 2026-08-06). The reader has to find a new left margin halfway down a page that is one column
   * of text.
   *
   * Widening the band does not lengthen a line of the hero: the measure is set inside by
   * `max-w-[46rem]` / `max-w-[20ch]` / `max-w-[60ch]`, which is the right place for it. The band
   * only decides where the column starts.
   */
  width = '4xl',
  eyebrow,
  title,
  lead,
  primary,
  secondary,
  children,
}: {
  bg?: BandBg;
  width?: keyof typeof BAND_WIDTH;
  eyebrow?: string;
  title: React.ReactNode;
  lead?: React.ReactNode;
  primary?: { href: string; label: string; onClick?: () => void; variant?: ButtonVariant };
  secondary?: { href: string; label: string; variant?: ButtonVariant };
  children?: React.ReactNode;
}) {
  return (
    <SectionBand bg={bg} width={width} className="pt-10 pb-12 md:pt-14 md:pb-16 animate-rise">
      <div className="max-w-[46rem]">
        {eyebrow && (
          <p className="mb-3 text-caption font-medium text-subtle">{eyebrow}</p>
        )}
        <h1 className="max-w-[20ch] text-balance text-h1 font-semibold text-text md:text-display">{title}</h1>
        {lead && (
          <div className="mt-4 max-w-[60ch] text-body text-muted">
            {lead}
          </div>
        )}
        {(primary || secondary) && (
          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
            {primary && (
              <Link href={primary.href} onClick={primary.onClick} className="w-full sm:w-auto">
                <Button variant={primary.variant || 'primary'} size="lg" className="w-full sm:w-auto">{primary.label}</Button>
              </Link>
            )}
            {secondary && (
              <Link href={secondary.href} className="w-full sm:w-auto">
                <Button variant={secondary.variant || 'secondary'} size="lg" className="w-full sm:w-auto">{secondary.label}</Button>
              </Link>
            )}
          </div>
        )}
      </div>
      {children && <div className="mt-12 w-full md:mt-16">{children}</div>}
    </SectionBand>
  );
}

/** A titled content section with consistent vertical rhythm. */
export function Section({
  bg = 'surface',
  width = '3xl',
  title,
  intro,
  children,
  className,
}: {
  bg?: BandBg;
  width?: keyof typeof BAND_WIDTH;
  title?: React.ReactNode;
  intro?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <SectionBand bg={bg} width={width} className={`py-16 md:py-24 scroll-mt-16 ${className ?? ''}`}>
      {(title || intro) && (
        <div className="mb-10">
          {title && <h2 className="text-h2 font-semibold text-text md:text-h1">{title}</h2>}
          {intro && <div className="mt-3 max-w-[60ch] text-body text-muted">{intro}</div>}
        </div>
      )}
      <div>{children}</div>
    </SectionBand>
  );
}

/** One numbered step in a flow. The counter is mono: it is an ordinal, i.e. data. */
export function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-5">
      <div
        className="flex h-9 w-9 flex-none items-center justify-center rounded-md border border-border bg-surface2 font-mono text-caption font-medium text-subtle"
        aria-hidden="true"
      >
        {n.toString().padStart(2, '0')}
      </div>
      <div className="space-y-1.5 pt-1">
        <h3 className="text-body font-semibold leading-tight text-text">{title}</h3>
        <p className="text-meta text-muted">{children}</p>
      </div>
    </li>
  );
}

/** A feature/benefit card. */
export function FeatureCard({
  icon,
  title,
  children,
}: {
  icon: IconName;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="space-y-3 border-border bg-surface p-5">
      <div className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface2 text-subtle">
        <Icon name={icon} size={18} />
      </div>
      <h3 className="text-body font-semibold leading-tight text-text">{title}</h3>
      <p className="text-meta text-muted">{children}</p>
    </Card>
  );
}

/** Closing CTA band. Light, bordered, one primary action. */
export function CtaBand({
  title,
  lead,
  primary,
  secondary,
  /** Same rule as `PageHero`: match the page. A third left edge is worse than a wide band. */
  width = '3xl',
}: {
  width?: keyof typeof BAND_WIDTH;
  title: React.ReactNode;
  lead?: React.ReactNode;
  primary: { href: string; label: string };
  secondary?: { href: string; label: string };
}) {
  return (
    <SectionBand bg="surface2" width={width} className="scroll-mt-16 py-16 md:py-24">
      <h2 className="max-w-[20ch] text-balance text-h1 font-semibold text-text">{title}</h2>
      {lead && <p className="mt-3 max-w-[60ch] text-body text-muted">{lead}</p>}
      <div className="mt-8 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
        <Link href={primary.href}>
          <Button variant="primary" size="lg">{primary.label}</Button>
        </Link>
        {secondary && (
          <Link href={secondary.href}>
            <Button variant="secondary" size="lg">{secondary.label}</Button>
          </Link>
        )}
      </div>
    </SectionBand>
  );
}
