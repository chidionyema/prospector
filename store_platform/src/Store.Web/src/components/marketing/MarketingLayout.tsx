import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { Button, Logo, Icon } from '@/components/ui';
import { CartButton } from '@/components/cart/CartButton';
import { LEGAL, BRAND } from '@/lib/config';
import { useDisclosure } from '@/lib/useDisclosure';

/**
 * High-fidelity shell for the Mumchimp marketing pages. Purely presentational.
 * Standardises the pure-white canvas with the noise grain filter (0.02 opacity).
 *
 * IDENTITY-BLINDNESS: never carries or fetches user identity.
 */

/** The public marketing nav, every entry points at a page that exists. */
export const MARKETING_NAV = [
  { href: '/', label: 'Catalog' },
  // `/ideas` is here rather than only in the sitemap because it is the hub every `/ideas/<slug>`
  // landing hangs off: linked from the chrome, each landing is two clicks from the home page
  // instead of being reachable only from a sitemap and its siblings.
  // Label shortened from "Browse by category": at 14px the four-word item was wider than the
  // other three combined, so the nav read as one long phrase rather than four destinations.
  { href: '/ideas', label: 'Categories' },
  { href: '/how-it-works', label: 'How it works' },
  // Promoted out of the footer (2026-08-06). This shop's entire claim is that most ideas are
  // rejected; the log of what got rejected and why is the evidence for that claim, and it was
  // reachable only from a footer column. It is the strongest trust asset on the site.
  { href: '/kill-log', label: 'Kill log' },
  { href: '/faq', label: 'FAQ' },
] as const;

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

      {/*
        White chrome (brand v3, 2026-08-06). The near-black band is gone.
        A dark header on an otherwise white store is a second colour system: everything placed in
        it needed inverted text tokens (--on-band, --on-band-muted, --on-band-faint) and its own
        button variants, and the wordmark needed an `onDark` mode. Removing it deletes all three.

        `shadow-1` appears only once scrolled, so the shadow means "there is content underneath
        this" rather than being decoration -- the elevation rule in §5.3.
      */}
      <header
        className={`sticky top-0 z-30 w-full border-b border-border bg-bg/90 backdrop-blur-md pt-[env(safe-area-inset-top)] transition-shadow duration-200 ${
          scrolled ? 'shadow-1' : ''
        }`}
      >
        <div className={`${SHELL} flex h-16 items-center justify-between gap-4`}>
          {/* Left: Brand & Main Nav */}
          <div className="flex items-center gap-10">
            <Link href="/" className="flex items-center transition-opacity hover:opacity-80" aria-label={`${BRAND.name} home`}>
              <Logo className="text-h2" />
            </Link>

            <nav className="hidden items-center gap-7 md:flex">
              {MARKETING_NAV.map((item) => (
                <Link key={item.href} href={item.href} className="text-meta font-medium text-muted transition-colors hover:text-text">{item.label}</Link>
              ))}
            </nav>
          </div>

          {/* Right: Actions */}
          <div className="flex h-full items-center gap-1">
            {/* Renders nothing until there is something in it, see CartButton. */}
            <CartButton />

            {/* Deliberately a plain link with a fixed label, so the header keeps the
                identity-blindness noted above: it fetches nothing, renders the same markup for
                every visitor, and stays cacheable. A "Sign in / Your account" toggle would have
                to wait for the session before it could choose, so every returning customer would
                watch it flip after hydration, and every page in the site would depend on the
                session resolving. /account itself decides which of the two it is.

                A ghost link, not a bordered box: the header should offer exactly one thing that
                looks clickable-as-a-control, and on a shop that is the cart. */}
            <Link
              href="/account"
              className="hidden items-center gap-1.5 rounded-md px-2 py-1.5 text-meta font-medium text-muted transition-colors hover:text-text md:inline-flex"
            >
              <Icon name="account" size={18} />
              Account
            </Link>
            <div className="flex h-full items-center md:hidden">
              <button
                ref={menuButtonRef}
                type="button"
                className="inline-flex items-center justify-center rounded-md p-2 text-muted transition-colors hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
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
          <div id="marketing-menu" className="animate-rise border-t border-border bg-surface shadow-2 md:hidden">
            <nav aria-label="Marketing" className="mx-auto flex flex-col divide-y divide-border px-4 sm:px-6">
              <div className="py-2">
                {MARKETING_NAV.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMenuOpen(false)}
                    className="block py-3 text-body font-medium text-text"
                  >
                    {item.label}
                  </Link>
                ))}
                {/* The desktop Account link is hidden below md, so the mobile menu carries it. */}
                <Link
                  href="/account"
                  onClick={() => setMenuOpen(false)}
                  className="block py-3 text-body font-medium text-text"
                >
                  Account
                </Link>
              </div>
              <div className="py-4">
                <Link href="/" onClick={() => setMenuOpen(false)}>
                  <Button fullWidth size="lg">Browse the packs</Button>
                </Link>
              </div>
            </nav>
          </div>
        )}
      </header>

      {/* Full-width main: children own their contrast bands. */}
      <main id="main" className="bg-bg">{children}</main>

      {/*
        Footer. Column headings are `text-caption font-medium text-subtle` in sentence case --
        previously orange, uppercase, letterspaced and bold, i.e. four emphasis devices on a word
        whose only job is to label a list of five links.

        The disclaimer moved from `text-muted/50` to `text-subtle`. At 50% opacity over #FAFAFA
        that paragraph computed to roughly 2.4:1, below the 4.5:1 AA floor -- and it is the
        paragraph that says the packs are not financial advice, which is the one piece of copy on
        the site that has to be readable.
      */}
      <footer className="border-t border-border bg-surface2 pt-16 pb-[calc(3rem+env(safe-area-inset-bottom))]">
        <div className={SHELL}>

          <div className="mb-12 max-w-md">
            <Logo className="mb-3 text-h2" />
            <p className="text-meta text-muted">
              {/* "£49 each" removed: the footer renders on every page including ones with no
                  catalogue loaded, and the shelf has not been one price since the segment
                  ladder shipped. The live figures live on /pricing, which reads them. */}
              Business ideas that survived the filter. Fully sourced, ready to build.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-8 border-t border-border pt-10 md:grid-cols-3">

            <div>
              <h3 className="mb-4 text-caption font-medium text-subtle">Store</h3>
              <ul className="flex flex-col gap-3">
                <li><Link href="/" className="text-meta text-muted transition-colors hover:text-text">Catalog</Link></li>
                <li><Link href="/ideas" className="text-meta text-muted transition-colors hover:text-text">Categories</Link></li>
                <li><Link href="/how-it-works" className="text-meta text-muted transition-colors hover:text-text">How it works</Link></li>
                <li><Link href="/kill-log" className="text-meta text-muted transition-colors hover:text-text">Kill log</Link></li>
                {/* `/about` had ZERO inbound links from anywhere on the site (verified 2026-08-06:
                    `href="/about"` matched no file under src/). The page has existed and been
                    maintained the whole time -- it was simply unreachable except by typing the URL,
                    which means a visitor asking the single most common question about an anonymous
                    shop ("who is running this?") had no way to find the page that answers it. */}
                <li><Link href="/about" className="text-meta text-muted transition-colors hover:text-text">Who makes this</Link></li>
                <li><Link href="/faq" className="text-meta text-muted transition-colors hover:text-text">FAQ</Link></li>
              </ul>
            </div>

            <div>
              <h3 className="mb-4 text-caption font-medium text-subtle">Legal</h3>
              <ul className="flex flex-col gap-3">
                <li><Link href="/terms" className="text-meta text-muted transition-colors hover:text-text">Terms of Service</Link></li>
                <li><Link href="/privacy" className="text-meta text-muted transition-colors hover:text-text">Privacy Policy</Link></li>
                <li><Link href="/refund" className="text-meta text-muted transition-colors hover:text-text">Refund Policy</Link></li>
              </ul>
            </div>

            <div>
              <h3 className="mb-4 text-caption font-medium text-subtle">Contact</h3>
              <ul className="flex flex-col gap-3">
                <li><a href={`mailto:${LEGAL.supportEmail}`} className="break-all text-meta text-muted transition-colors hover:text-text">{LEGAL.supportEmail}</a></li>
              </ul>
            </div>

          </div>

          <div className="mt-10 border-t border-border pt-8">
            <p className="text-caption text-subtle">
              &copy; 2026 {BRAND.name}. All rights reserved.
            </p>
            <p className="mt-4 max-w-[80ch] text-caption leading-relaxed text-subtle">
              Mumchimp packs are digital research products sold for information only, not financial, legal, or investment advice. Each pack is a grounded analysis with cited sources. We don&apos;t guarantee any business outcome. Payments are processed securely by Stripe.
            </p>
          </div>

        </div>
      </footer>
    </div>
  );
}
