import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { Button, Logo, Icon } from '@/components/ui';
import { LEGAL, BRAND } from '@/lib/config';
import { useDisclosure } from '@/lib/useDisclosure';

/**
 * High-fidelity shell for GTM marketing pages. Purely presentational.
 * Standardises the pure-white canvas with the noise grain filter (0.02 opacity).
 *
 * IDENTITY-BLINDNESS (P0): never carries or fetches user identity.
 * WEB-COPY-TRUTHLOCK: from /web, `node scripts/check-conformance.mjs` enforces lexicon.
 * Avoid "escrow" in public copy (L-03); use "funds secured" or "auth-hold".
 * Qualify "verified" (e.g. "Verified Identity") — no naked "verified".
 */

/** The marketing IA — split utility groups per 2026-06-08 spec. */
export const MARKETING_MECHANICS = [
  { href: '/', label: 'Catalog' },
  { href: '/faq', label: 'FAQ' },
] as const;

export const MARKETING_ROLES = [] as const;

interface MarketingLayoutProps {
  children: React.ReactNode;
}

export default function MarketingLayout({ children }: MarketingLayoutProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const { triggerRef: menuButtonRef } = useDisclosure(menuOpen, () => setMenuOpen(false));

  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const SHELL = 'mx-auto max-w-7xl px-4 sm:px-6 lg:px-8';

  return (
    <div className="min-h-dvh bg-bg font-sans text-text antialiased">
      <a
        href="#main"
        className="sr-only focus-visible:not-sr-only focus-visible:absolute focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-primary focus-visible:px-4 focus-visible:py-2 focus-visible:text-on-primary"
      >
        Skip to content
      </a>

      {/* 1. STICKY "PRIVATE CLUB" NAVIGATION */}
      <header
        className={`sticky top-0 z-50 w-full transition-all duration-200 border-b pt-[env(safe-area-inset-top)] ${
          scrolled ? 'bg-white/80 backdrop-blur-md border-border/60 shadow-sm' : 'bg-white border-transparent shadow-none'
        }`}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 h-16">
          {/* Left: Brand & Main Nav */}
          <div className="flex items-center gap-10">
            <Link href="/" className="flex items-center gap-4 transition-opacity hover:opacity-80" aria-label={`${BRAND.name} home`}>
              <Logo monogramOnly />
              <span className="font-serif font-semibold tracking-tight text-lg hidden sm:block">
                {BRAND.name}
              </span>
            </Link>

            <nav className="hidden md:flex items-center gap-6">
              <Link href="/for-buyers" className="font-semibold text-sm text-muted hover:text-text transition-colors">Get a warm intro</Link>
              <Link href="/pricing" className="font-semibold text-sm text-muted hover:text-text transition-colors">Pricing</Link>
              <Link href="/how-it-works" className="font-semibold text-sm text-muted hover:text-text transition-colors">The Framework</Link>
            </nav>
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-6 h-full">
            <div className="flex items-center md:hidden h-full">
              <button
                ref={menuButtonRef}
                type="button"
                className="inline-flex items-center justify-center p-2 text-muted hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
                aria-label={menuOpen ? 'Close menu' : 'Open menu'}
                aria-expanded={menuOpen}
                aria-controls="marketing-menu"
                onClick={() => setMenuOpen((o) => !o)}
              >
                <Icon name={menuOpen ? 'close' : 'menu'} />
              </button>
            </div>
          </div>
        </div>

        {menuOpen && (
          <div id="marketing-menu" className="border-t border-border bg-white md:hidden shadow-lg animate-rise">
            <nav aria-label="Marketing" className="mx-auto flex flex-col divide-y divide-border px-6 py-4">
              <div className="py-4 space-y-4">
                <p className="text-[10px] font-mono font-semibold uppercase tracking-widest text-muted opacity-60 px-2">Product</p>
                {MARKETING_MECHANICS.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMenuOpen(false)}
                    className="block px-2 py-2 font-mono text-xs font-semibold text-muted hover:text-text"
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
              <div className="py-6 space-y-4">
                <p className="text-[10px] font-mono font-semibold uppercase tracking-widest text-muted opacity-60 px-2">Join</p>
                {MARKETING_ROLES.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMenuOpen(false)}
                    className="block px-2 py-2 font-mono text-xs font-semibold text-muted hover:text-text"
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
              <div className="py-6">
                <Link href="/register?role=Buyer" onClick={() => setMenuOpen(false)}>
                  <Button fullWidth className="uppercase tracking-[0.2em] font-mono text-[10px] h-12 rounded-none bg-text text-bg border-none font-semibold">
                    Request Access
                  </Button>
                </Link>
              </div>
            </nav>
          </div>
        )}
      </header>

      {/* Full-width main: children own their contrast bands. */}
      <main id="main" className="bg-bg">{children}</main>

      {/* 5. WORLD-CLASS FOOTER (Institutional / Ledger Aesthetic) */}
      <footer className="bg-surface2 border-t border-border pt-16 md:pt-24 pb-[calc(3rem+env(safe-area-inset-bottom))] overflow-hidden relative">
        <div className={`${SHELL} relative z-10`}>
          
          {/* Top Section: Brand Statement */}
          <div className="flex flex-col md:flex-row justify-between items-start gap-12 mb-16 md:mb-20">
            <div className="max-w-md text-left">
              <Logo className="text-3xl mb-6 text-text" />
              <p className="text-xl font-normal text-muted leading-relaxed">
                Replacing the cold outreach gamble with aligned incentives and verifiable trust.
              </p>
            </div>
          </div>

          {/* Middle Section: Strict Ledger Grid */}
          <div className="grid grid-cols-1 md:grid-cols-4 border-t border-border md:divide-x md:divide-border text-left">
            
            {/* Column 1 */}
            <div className="py-8 md:py-10 md:pr-8 border-b border-border md:border-b-0">
              <h3 className="font-mono text-[10px] uppercase tracking-wide text-eyebrow mb-6 md:mb-8 font-bold">Network</h3>
              <ul className="flex flex-col gap-4">
                <li><Link href="/for-buyers" className="text-xs text-muted hover:text-text transition-colors">Get an Introduction</Link></li>
                <li><Link href="/for-connectors" className="text-xs text-muted hover:text-text transition-colors">Offer Introductions</Link></li>
                <li><Link href="/board" className="text-xs text-muted hover:text-text transition-colors">Review Queue</Link></li>
              </ul>
            </div>

            {/* Column 2 */}
            <div className="py-8 md:py-10 md:px-8 border-b border-border md:border-b-0">
              <h3 className="font-mono text-[10px] uppercase tracking-wide text-eyebrow mb-6 md:mb-8 font-bold">Resources</h3>
              <ul className="flex flex-col gap-4">
                <li><Link href="/pricing" className="text-xs text-muted hover:text-text transition-colors">Pricing & Auth-Hold</Link></li>
                <li><Link href="/how-it-works" className="text-xs text-muted hover:text-text transition-colors">Methodology</Link></li>
                <li><Link href="/faq" className="text-xs text-muted hover:text-text transition-colors">FAQ</Link></li>
              </ul>
            </div>

            {/* Column 3 */}
            <div className="py-8 md:py-10 md:px-8 border-b border-border md:border-b-0">
              <h3 className="font-mono text-[10px] uppercase tracking-wide text-eyebrow mb-6 md:mb-8 font-bold">Legal</h3>
              <ul className="flex flex-col gap-4">
                <li><Link href="/terms" className="text-xs text-muted hover:text-text transition-colors">Terms of Service</Link></li>
                <li><Link href="/privacy" className="text-xs text-muted hover:text-text transition-colors">Privacy Policy</Link></li>
                <li><Link href="/remove-me" className="text-xs text-muted hover:text-text transition-colors">Data Opt-Out</Link></li>
              </ul>
            </div>

            {/* Column 4 */}
            <div className="py-8 md:py-10 md:pl-8">
              <h3 className="font-mono text-[10px] uppercase tracking-wide text-eyebrow mb-6 md:mb-8 font-bold">Contact</h3>
              <ul className="flex flex-col gap-4">
                <li><a href={`mailto:${LEGAL.supportEmail}`} className="text-xs text-muted hover:text-text transition-colors break-all">{LEGAL.supportEmail}</a></li>
                <li><a href="https://x.com/theintroexchange" target="_blank" rel="noreferrer" className="text-xs text-muted hover:text-text transition-colors">X/Twitter</a></li>
              </ul>
            </div>

          </div>

          {/* Bottom Section: Metadata */}
          <div className="border-t border-border pt-8 mt-4 flex flex-col md:flex-row justify-between items-center gap-8 text-left">
            <p className="font-mono text-[10px] text-muted uppercase tracking-wide font-bold">
              &copy; 2026 {BRAND.name}. All rights reserved.
            </p>
            <div className="flex items-center gap-4">
              <div className="w-8 md:w-12 h-px bg-border"></div>
              <p className="font-mono text-[10px] text-text uppercase tracking-wide font-bold">
                London &bull; San Francisco
              </p>
              <div className="w-8 md:w-12 h-px bg-border"></div>
            </div>
          </div>

          {/* Facilitator disclaimer (WR-014) */}
          <p className="mt-12 md:mt-16 text-[10px] font-medium text-muted/50 leading-relaxed text-left max-w-5xl tracking-wide">
            We cannot guarantee any introduction, reply, meeting, or outcome, nobody honestly can. We&apos;re not a bank or payment institution and we never hold your money: your bank authorises the hold and Stripe processes payments.
          </p>

        </div>
      </footer>
    </div>
  );
}
