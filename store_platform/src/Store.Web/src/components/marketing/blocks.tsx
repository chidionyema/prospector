import React from 'react';
import Link from 'next/link';
import { Button, Card, Icon, cx } from '@/components/ui';
import type { IconName, ButtonVariant } from '@/components/ui';

/**
 * Small presentational blocks shared across the WR-014 GTM marketing pages.
 * Semantic tokens only (raw hex/palette fails `npm run conformance`). No data, no API — these
 * are pure layout/typography so the pages stay static and Pact-free.
 */

/**
 * Full-bleed section background with the standard inner content container.
 * Redesigned (2026-06-08) for premium institutional aesthetic.
 */
type BandBg = 'surface' | 'surface2' | 'band' | 'vault-wash' | 'white' | 'bg';
const BAND_BG: Record<BandBg, string> = {
  surface: 'bg-surface',
  surface2: 'bg-surface2',
  band: 'bg-band',
  'vault-wash': 'bg-surface2', // Unified wash to off-white
  white: 'bg-white',
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
      <div className={`mx-auto ${BAND_WIDTH[width]} px-6 md:px-8 lg:px-10 ${className ?? ''}`}>
        {children}
      </div>
    </section>
  );
}

/** A page hero: outcome-driven headline + monospace eyebrow. Clear mobile viewport. */
export function PageHero({
  bg = 'white',
  eyebrow,
  title,
  lead,
  primary,
  secondary,
  children,
}: {
  bg?: BandBg;
  eyebrow?: string;
  title: React.ReactNode;
  lead?: React.ReactNode;
  primary?: { href: string; label: string; onClick?: () => void; variant?: ButtonVariant };
  secondary?: { href: string; label: string; variant?: ButtonVariant };
  children?: React.ReactNode;
}) {
  return (
    <SectionBand bg={bg} width="4xl" className="pt-12 pb-4 md:pt-32 md:pb-24 lg:pt-40 lg:pb-32 min-h-[calc(100dvh-4rem)] md:min-h-0 flex flex-col justify-start md:justify-center items-center animate-rise text-center">
      <div className="flex flex-col items-center justify-center flex-grow w-full">
        {eyebrow && (
          <p className="font-mono text-xs font-semibold uppercase tracking-wide text-muted mb-4 md:mb-6">{eyebrow}</p>
        )}
        <h1 className="max-w-[20ch] text-4xl md:text-6xl lg:text-[5.5rem] font-bold tracking-tight text-text leading-[1.15] mb-6 animate-fade-in-up text-balance">{title}</h1>
        {lead && (
          <div className="max-w-[50ch] text-base md:text-xl font-normal leading-relaxed text-text/80 mb-8 md:mb-12 animate-fade-in-up [animation-delay:200ms]">
            {lead}
          </div>
        )}
        {(primary || secondary) && (
          <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-center w-full px-4 sm:px-0">
            {primary && (
              <Link href={primary.href} onClick={primary.onClick} className="w-full sm:w-auto">
                <Button variant={primary.variant || "primary"} className="h-14 w-full sm:w-auto px-8 text-sm font-bold uppercase tracking-wide">{primary.label}</Button>
              </Link>
            )}
            {secondary && (
              <Link href={secondary.href} className="w-full sm:w-auto">
                <Button variant={secondary.variant || "secondary"} className="h-14 w-full sm:w-auto px-8 text-sm font-bold uppercase tracking-wide border-border">{secondary.label}</Button>
              </Link>
            )}
          </div>
        )}
      </div>
      {children && <div className="w-full mt-12 md:mt-16">{children}</div>}
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
    <SectionBand bg={bg} width={width} className={`py-12 md:py-24 scroll-mt-16 ${className ?? ''}`}>
      {(title || intro) && (
        <div className="mb-12">
          {title && <h2 className="text-3xl md:text-4xl font-black tracking-tight text-text mb-6">{title}</h2>}
          {intro && <div className="text-base md:text-lg font-normal leading-relaxed text-text/80">{intro}</div>}
        </div>
      )}
      <div>{children}</div>
    </SectionBand>
  );
}

/** One numbered step in a flow: high-contrast Monospace markers. */
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
    <li className="flex gap-8 group">
      <div
        className="flex h-12 w-12 flex-none items-center justify-center rounded-md border border-border bg-white text-sm font-bold text-text shadow-sm transition-transform group-hover:scale-110"
        aria-hidden="true"
      >
        {n.toString().padStart(2, '0')}
      </div>
      <div className="space-y-2 pt-1">
        <h3 className="text-lg font-bold text-text leading-tight">{title}</h3>
        <p className="text-sm leading-relaxed text-muted">{children}</p>
      </div>
    </li>
  );
}

/** A feature/benefit card: minimalist shadow + serif titles. */
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
    <Card className="space-y-4 p-8 bg-white border-border rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] transition-all card-transition">
      <div className="inline-flex h-12 w-12 items-center justify-center rounded-lg bg-primary/5 text-primary border border-primary/10">
        <Icon name={icon} size={24} />
      </div>
      <h3 className="text-lg font-bold text-text leading-tight">{title}</h3>
      <p className="text-sm leading-relaxed text-text/80">{children}</p>
    </Card>
  );
}

/** Closing CTA band: massive whitespace + deep Blue brand lock. */
export function CtaBand({
  title,
  lead,
  primary,
  secondary,
}: {
  title: React.ReactNode;
  lead?: React.ReactNode;
  primary: { href: string; label: string };
  secondary?: { href: string; label: string };
}) {
  return (
    <SectionBand bg="band" width="3xl" className="py-24 sm:py-32 scroll-mt-16">
      <h2 className="max-w-[15ch] text-balance text-4xl md:text-5xl font-bold tracking-tight text-white leading-none mb-8">{title}</h2>
      {lead && <p className="mt-4 max-w-xl text-lg font-normal leading-relaxed text-on-band-muted">{lead}</p>}
      <div className="mt-12 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
        <Link href={primary.href}>
          <Button variant="inverse" className="h-12 px-8 text-sm font-semibold">{primary.label}</Button>
        </Link>
        {secondary && (
          <Link href={secondary.href}>
            <Button variant="inverseGhost" className="h-12 px-8 text-sm font-semibold">{secondary.label}</Button>
          </Link>
        )}
      </div>
    </SectionBand>
  );
}
