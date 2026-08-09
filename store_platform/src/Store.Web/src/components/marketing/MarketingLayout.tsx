import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { Button, Logo, Icon } from '@/components/ui';
import { CartButton } from '@/components/cart/CartButton';
import { LEGAL, BRAND } from '@/lib/config';
import { SEARCH_OPEN_EVENT } from '@/lib/searchEvent';
import { RESEARCH_STATS } from '@/lib/stats';
import { useDisclosure } from '@/lib/useDisclosure';

/**
 * High-fidelity shell for the Mumchimp marketing pages. Purely presentational.
 * Standardises the pure-white canvas with the noise grain filter (0.02 opacity).
 *
 * IDENTITY-BLINDNESS: never carries or fetches user identity.
 */

/** The public marketing nav, every entry points at a page that exists. */
export const MARKETING_NAV = [
  // "Catalogue", not "Catalog". The site is written in British English throughout (the graph on
  // /ideas already labels itself "Catalogue categories"), and the nav and footer were the only
  // two places carrying the American spelling.
  { href: '/', label: 'Catalogue' },
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

/**
 * Is `href` the section the visitor is currently in?
 *
 * WHY THIS EXISTS. Every nav item rendered `text-muted` on every page, so the chrome never told
 * anyone where they were. On a site with five destinations and a lot of cross-linking between them
 * (`/pack` sends people to `/how-it-works`, `/how-it-works` to `/kill-log`, `/kill-log` back to
 * the shelf) that is the single cheapest orientation cue available, and it was absent.
 *
 * PREFIX MATCH, EXCEPT FOR `/`. `/ideas/<slug>` has to light up `Categories`, because a landing
 * page IS the categories section -- an exact match would leave a visitor on the busiest branch of
 * the site with no item lit at all. `/` is special-cased to an exact comparison for the opposite
 * reason: every path on the site starts with a slash, so a prefix rule would mark `Catalogue`
 * active on all five pages and the state would carry no information.
 *
 * Compared against `router.pathname`, the ROUTE pattern (`/ideas/[slug]`), not `asPath`: `asPath`
 * carries the query string, so `/?search=1` -- which the header's own search button navigates to
 * from every other page -- would stop matching `/` and the item would go dark at the exact moment
 * the visitor arrived at the catalogue.
 */
function isActivePath(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

interface MarketingLayoutProps {
  children: React.ReactNode;
}

export default function MarketingLayout({ children }: MarketingLayoutProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const { triggerRef: menuButtonRef } = useDisclosure(menuOpen, () => setMenuOpen(false));
  const router = useRouter();

  /* SEARCH, PROMOTED INTO THE CHROME.
     The catalogue has had full-text search since the command palette shipped, and it was
     reachable by exactly two routes: Cmd-K / `/`, and a trigger that sits in the toolbar above
     the shelf. A phone has neither a Cmd key nor that toolbar in view, so on the device most of
     this traffic arrives on, a shop with 63 products offered no way to look one up.

     The header cannot own the palette itself: it renders on /faq, /terms, /pack/[id] and
     everything else, none of which hold the catalogue state the palette searches. So the button
     is a dispatcher. On the catalogue it fires the window event `useCommandPalette` listens for;
     anywhere else there is no listener at all, and it navigates to `/?search=1`, which
     `CatalogBrowser` reads on mount and opens the palette itself. Both paths end in the same
     open palette, and neither imports the other. */
  const openSearch = useCallback(() => {
    setMenuOpen(false);
    if (router.pathname === '/') {
      window.dispatchEvent(new Event(SEARCH_OPEN_EVENT));
    } else {
      void router.push('/?search=1');
    }
  }, [router]);

  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // §3.4: 1200px max, 24px gutters. Was `max-w-7xl px-4 sm:px-6 lg:px-8` -- 1280px with a gutter
  // that stepped 16 -> 24 -> 32px across breakpoints. The step was the problem, not the width: a
  // three-value gutter means the grid's outer margin is a different size on almost every device,
  // so nothing on the page can be aligned to it reliably. One value, at every width.
  const SHELL = 'mx-auto max-w-[1200px] px-6';

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

        The hairline appears only once scrolled, so the rule means "there is content passing under
        this" rather than being decoration.

        It was a shadow, and then for a while it was nothing at all. §3.4 (tokens.css, 2026-08-08)
        retired box-shadows sitewide -- `--shadow-1`/`--shadow-2` are `none` and depth is a surface
        step plus a hairline -- and the sweep that stripped the class from this call site left
        `scrolled ? '' : ''` behind: a live scroll listener (see `onScroll` above) feeding a pair
        of empty strings, plus a border drawn identically at every scroll position. The header had
        no scroll feedback of any kind, and nothing failed, because a dead ternary renders.

        Only the border COLOUR changes, never whether the border is there. Adding and removing the
        1px box would move the whole page by a pixel on the first scroll of every visit.
      */}
      <header
        className={`sticky top-0 z-30 w-full border-b bg-bg/90 backdrop-blur-md pt-[env(safe-area-inset-top)] transition-colors duration-200 ${
          scrolled ? 'border-border' : 'border-transparent'
        }`}
      >
        {/* COMPACT ON SCROLL. `h-16` (64px) is the resting height; past the same `scrolled`
            threshold that turns the hairline on (4px, above), it steps to `h-14` (56px) -- an
            8px reclaim, not a redesign. The logo and nav sizes are untouched: shrinking the row
            instead of the content keeps every tap target's own 44px floor intact rather than
            scaling toward it. `transition-[height]` rides the same 200ms as the border so the
            two reads as one event, not two. */}
        <div
          className={`${SHELL} flex items-center justify-between gap-4 transition-[height] duration-200 ${
            scrolled ? 'h-14' : 'h-16'
          }`}
        >
          {/* Left: Brand & Main Nav */}
          <div className="flex items-center gap-10">
            <Link href="/" className="flex items-center transition-opacity hover:opacity-80" aria-label={`${BRAND.name} home`}>
              <Logo className="text-h2" />
            </Link>

            <nav className="hidden items-center gap-7 md:flex">
              {MARKETING_NAV.map((item) => {
                const active = isActivePath(router.pathname, item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    /* `aria-current="page"` is the state; the ink and the rule are how it is
                       drawn. Weight is deliberately NOT the signal -- the items are already
                       `font-medium` and bumping the active one to semibold reflows the whole nav
                       by a pixel or two on every navigation. Full-strength text against muted,
                       plus a 2px rule sitting on the header's own bottom border, changes nothing
                       about the box. */
                    aria-current={active ? 'page' : undefined}
                    /* `h-full`, not a hardcoded `h-16`: the active-state underline is pinned to
                       `-bottom-px` of THIS box, so it has to track the header row's real height
                       rather than assume one -- the row now steps to `h-14` once `scrolled`
                       (compact-on-scroll, above), and a fixed h-16 here would overflow it and
                       throw the underline off the header's own bottom edge. */
                    className={`relative flex h-full items-center text-meta font-medium transition-colors ${
                      active
                        ? 'text-text after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-text'
                        : 'text-muted hover:text-text'
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>

          {/* Right: Actions */}
          <div className="flex h-full items-center gap-2">
            {/* At every width, including mobile -- see `openSearch` above for why it is a
                dispatcher and not the palette. The word is hidden below lg because the header
                also carries five nav items at that width; the magnifier alone is the one icon
                that needs no label.

                `min-h-11 min-w-11` (44px, the WCAG 2.5.8 floor): below `lg` this button is just
                the 18px glyph plus `px-2 py-1.5`, which never adds up to 44px on either axis, so
                the minimum has to be stated explicitly rather than left to padding. `justify-center`
                keeps the glyph centred once the box is wider than its own content at the widths
                where the "Search" label is hidden. */}
            <button
              type="button"
              onClick={openSearch}
              aria-label="Search the catalogue"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-meta font-medium text-muted transition-colors hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              <Icon name="search" size={18} />
              <span className="hidden lg:inline">Search</span>
            </button>

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
                /* Matches the 44px WCAG 2.5.8 floor the search button states explicitly above --
                   `p-2` (8px) + the default 20px glyph only reaches ~36px, under the same floor
                   this header already enforces for its neighbour.

                   VISIBLE "Menu"/"Close" LABEL, not icon-alone. This button only ever renders
                   below `md`, next to four other header controls (search glyph, cart, account
                   link) that either carry their own text or are unambiguous at a glance -- the
                   hamburger glyph is the one shape on the row a first-time visitor cannot be
                   assumed to already know. `aria-label` is gone rather than kept alongside the
                   text: with the text always visible here (unlike the Search button's, which
                   hides below `lg`), keeping both would give the control two different
                   accessible names and fail WCAG 2.5.3 Label in Name. `Icon.tsx:128` always sets
                   `aria-hidden="true"` on the glyph, so the accessible name here is just the
                   word. */
                className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-meta font-medium text-muted transition-colors hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                aria-expanded={menuOpen}
                aria-controls="marketing-menu"
                onClick={() => setMenuOpen((o) => !o)}
              >
                <Icon name={menuOpen ? 'close' : 'menu'} size={18} />
                {menuOpen ? 'Close' : 'Menu'}
              </button>
            </div>
          </div>
        </div>

        {menuOpen && (
          <div id="marketing-menu" className="animate-rise border-t border-border bg-surface md:hidden">
            <nav aria-label="Marketing" className="mx-auto flex flex-col divide-y divide-border px-4 sm:px-6">
              <div className="py-2">
                {/* Same state, drawn differently, because the drawer has no bottom border for a
                    rule to sit on and every item in it is already full-strength text. A left rule
                    in the same ink is the equivalent mark on a stacked list. */}
                {MARKETING_NAV.map((item) => {
                  const active = isActivePath(router.pathname, item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setMenuOpen(false)}
                      aria-current={active ? 'page' : undefined}
                      className={`block py-3 text-body font-medium ${
                        active ? 'border-l-2 border-l-text pl-3 text-text' : 'text-muted'
                      }`}
                    >
                      {item.label}
                    </Link>
                  );
                })}
                {/* The desktop Account link is hidden below md, so the mobile menu carries it. */}
                <Link
                  href="/account"
                  onClick={() => setMenuOpen(false)}
                  className="block py-3 text-body font-medium text-text"
                >
                  Account
                </Link>
              </div>
              {/* Was a full-width "Browse the packs" button pointing at `/` -- the same
                  destination as the "Catalogue" item three rows above it, in a drawer whose whole
                  job is to disambiguate destinations. The drawer's one emphasised action is now
                  the thing the drawer did not otherwise offer. */}
              <div className="py-4">
                <Button fullWidth size="lg" onClick={openSearch}>
                  <Icon name="search" size={18} />
                  Search the catalogue
                </Button>
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

        They are <h2>, not <h3>. The footer renders on every route, so its heading level is fixed
        while the page above it is not: on a route whose content stops at <h1> (/account is the one
        axe caught), an <h3> here skips a level and trips `heading-order`. h2 is the only level that
        is correct after any page, since every page has exactly one h1.

        The disclaimer moved from `text-muted/50` to `text-subtle`. At 50% opacity over #FAFAFA
        that paragraph computed to roughly 2.4:1, below the 4.5:1 AA floor -- and it is the
        paragraph that says the packs are not financial advice, which is the one piece of copy on
        the site that has to be readable.
      */}
      <footer className="border-t border-border bg-surface2 pt-16 pb-[calc(3rem+env(safe-area-inset-bottom))]">
        <div className={SHELL}>

          {/* THE FOOTER SAYS SOMETHING NO OTHER FOOTER SAYS.
              It was a logo, a one-line blurb, three columns of links and a copyright, which is the
              same footer every storefront on the internet ships and carries no signal that this
              particular shop is different from any of them. The tally fixes that for the price of
              two numbers we already hold: a reader who has scrolled to the bottom of any page on
              the site ends on the ratio the whole business is built on, in the kill colour and the
              survive colour, in mono.

              The kill figure is set larger than the survivor figure, deliberately and for the same
              reason it is on /about: any shop can print how many products it has, and only this one
              can print how many it threw away.

              `RESEARCH_STATS`, not the raw JSON, and NOT the number of packs on the shelf. These
              are historical totals over every dossier the engine ever wrote, so a build-time
              snapshot is correct for them; `published` moves with no redeploy and is why
              `lib/stats.ts` refuses to carry it. */}
          <div className="mb-12 flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
            <div className="max-w-md">
              <Logo className="mb-3 text-h2" />
              <p className="text-meta text-muted">
                {/* "£49 each" removed: the footer renders on every page including ones with no
                    catalogue loaded, and the shelf has not been one price since the segment
                    ladder shipped. The live figures live on /pricing, which reads them. */}
                Business ideas that survived the filter. Fully sourced, ready to build.
              </p>
            </div>
            <dl className="m-0 flex flex-none items-end gap-10">
              <div>
                <dt className="text-caption text-kill">killed</dt>
                <dd className="m-0 mt-1 font-mono text-h1 font-semibold leading-none tracking-tight text-text">
                  {RESEARCH_STATS.killed.toLocaleString('en-GB')}
                </dd>
              </div>
              <div>
                <dt className="text-caption text-survive">survived</dt>
                <dd className="m-0 mt-1 font-mono text-h2 font-semibold leading-none tracking-tight text-text">
                  {RESEARCH_STATS.survived.toLocaleString('en-GB')}
                </dd>
              </div>
            </dl>
          </div>

          <div className="grid grid-cols-2 gap-8 border-t border-border pt-10 md:grid-cols-3">

            <div>
              <h2 className="mb-4 text-caption font-medium text-subtle">Store</h2>
              {/* TAP TARGETS, WCAG 2.5.8. Measured at 26x18 ("FAQ") up to 65x18 ("Catalogue") --
                  these are nav-list items, not inline links in a sentence of prose, so the 44px
                  minimum applies and padding alone (there was none) never got there. The fix is
                  on the anchor, not the `li`: `inline-block py-[13px]` turns the 18px text line
                  into a 44px box (18 + 13 top + 13 bottom = 44, the exact floor, not a rounder
                  number chosen for its own sake). That 26px of new padding lands where the `ul`'s
                  `gap-3` (12px) used to be the only spacing between items, so the gap is dropped
                  to `gap-0` in trade: the padding boxes now touch, and the visible whitespace
                  between rows grows from 12px to 26px rather than to 12+26=38px. It is not
                  "unchanged", but it is the closest the rhythm gets without shipping a
                  sub-44px target. */}
              <ul className="flex flex-col gap-0">
                <li><Link href="/" className="inline-block py-[13px] text-meta text-muted transition-colors hover:text-text">Catalogue</Link></li>
                <li><Link href="/ideas" className="inline-block py-[13px] text-meta text-muted transition-colors hover:text-text">Categories</Link></li>
                <li><Link href="/how-it-works" className="inline-block py-[13px] text-meta text-muted transition-colors hover:text-text">How it works</Link></li>
                <li><Link href="/kill-log" className="inline-block py-[13px] text-meta text-muted transition-colors hover:text-text">Kill log</Link></li>
                {/* `/about` had ZERO inbound links from anywhere on the site (verified 2026-08-06:
                    `href="/about"` matched no file under src/). The page has existed and been
                    maintained the whole time -- it was simply unreachable except by typing the URL,
                    which means a visitor asking the single most common question about an anonymous
                    shop ("who is running this?") had no way to find the page that answers it. */}
                <li><Link href="/about" className="inline-block py-[13px] text-meta text-muted transition-colors hover:text-text">Who makes this</Link></li>
                <li><Link href="/faq" className="inline-block py-[13px] text-meta text-muted transition-colors hover:text-text">FAQ</Link></li>
              </ul>
            </div>

            {/* LEGAL IS SMALLER AND GREYER THAN STORE, deliberately.
                Both columns were `text-meta text-muted`, so "Terms of Service" and "Kill log" had
                identical weight, size and colour -- and on mobile the two columns sit side by
                side, which made the boilerplate exactly as prominent as the evidence this shop
                sells on. These links must be present and must be findable; they must not compete
                with the ones a buyer came for. `text-subtle` is the same token the disclaimer
                uses and clears 4.5:1 on --surface2 (`__tests__/categoryScale.test.ts` holds the
                floor for the scale it belongs to). */}
            <div>
              <h2 className="mb-4 text-caption font-medium text-subtle">Legal</h2>
              {/* Same tap-target fix as the Store column above (`inline-block py-[13px]`,
                  `gap-0` in trade for the padding), applied here because it was missed the
                  first time: these anchors carried no padding at all, so the "Store" list-item
                  fix left its sibling column right below it at the same sub-24px height it was
                  supposedly fixing site-wide. */}
              <ul className="flex flex-col gap-0">
                <li><Link href="/terms" className="inline-block py-[13px] text-caption text-subtle transition-colors hover:text-text">Terms of Service</Link></li>
                <li><Link href="/privacy" className="inline-block py-[13px] text-caption text-subtle transition-colors hover:text-text">Privacy Policy</Link></li>
                <li><Link href="/refund" className="inline-block py-[13px] text-caption text-subtle transition-colors hover:text-text">Refund Policy</Link></li>
              </ul>
            </div>

            <div className="col-span-2 md:col-span-1">
              <h2 className="mb-4 text-caption font-medium text-subtle">Contact</h2>
              <ul className="flex flex-col gap-3">
                {/* `break-all` broke the address INSIDE a word -- it rendered as
                    "support@mumchimp." / "com", because at 2 columns on a 375px screen the
                    column is ~160px and `break-all` will split at any character it reaches. An
                    email address split mid-domain reads as a typo on the one string a nervous
                    buyer uses to check the shop is real. `break-words` only breaks a word that
                    cannot fit at all, and the column is full-width below md so it never has to.
                    An explicit `<wbr/>` after the @ gives it a legal break point if a narrower
                    device ever appears. */}
                <li>
                  <a
                    href={`mailto:${LEGAL.supportEmail}`}
                    className="inline-block break-words py-[13px] text-meta text-muted transition-colors hover:text-text"
                  >
                    {LEGAL.supportEmail}
                  </a>
                </li>
              </ul>
            </div>

          </div>

          {/* THE SCROLL NO LONGER JUST ENDS.
              A reader who reaches the bottom of the footer has read the whole page and not
              bought; the last thing on screen was a copyright line. These are the two next steps
              that are honest to offer at that point -- the shelf, and the log of what we
              rejected -- and neither is a repeat of the hero's ask. */}
          <div className="mt-10 flex flex-col gap-3 border-t border-border pt-8 sm:flex-row sm:items-center">
            <Link href="/">
              <Button size="md">
                Browse the catalogue
                <Icon name="arrowRight" size={15} />
              </Button>
            </Link>
            <Link href="/kill-log">
              <Button size="md" variant="secondary">See what we killed</Button>
            </Link>
          </div>

          <div className="mt-10 border-t border-border pt-8">
            <p className="text-caption text-subtle">
              &copy; 2026 {BRAND.name}. All rights reserved.
            </p>
            {/*
              THE DISCLAIMER, one sentence visible and the rest behind a disclosure.
              It is four sentences of unstyled small print, and on a 375px screen it wrapped to
              nine lines -- the tallest single block in the footer, at the bottom of a page that
              already runs ~16,000px. Collapsing it is only defensible because of WHICH sentence
              stays: the one that says these are not financial, legal or investment advice. That
              is the sentence with legal weight and it is never behind a click. What folds away
              is the description of the product and the payment processor, both of which are
              stated at more length on /how-it-works and at the checkout.

              `<details>` and not a React toggle: it is open-able with no JavaScript, it is
              keyboard-operable and screen-reader-announced for free, and -- the reason that
              matters here -- its contents stay in the DOM and in the server HTML whether or not
              anyone opens it, so collapsing it does not remove the text from the page.
            */}
            <p className="mt-4 max-w-[80ch] text-caption leading-relaxed text-subtle">
              Mumchimp packs are sold for information only, not financial, legal, or investment advice.
            </p>
            <details className="group mt-2 max-w-[80ch]">
              {/* NOT `textLinkClass()`, and not an accent-coloured underline. This is a
                  disclosure toggle, not a link into a sentence: it navigates nowhere, and the
                  house inline-link treatment is reserved for things that do
                  (`__tests__/storefrontDesignContract.test.ts`, "uses ONE inline-link
                  treatment"). A caret that rotates on open is the affordance; the label stays in
                  the same ink as the paragraph it belongs to. */}
              <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-caption text-subtle transition-colors hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
                {/* `plus`, rotated 45deg when open, so the mark itself becomes the close
                    affordance. The icon set carries no chevron and this needs no new one. */}
                <Icon
                  name="plus"
                  size={13}
                  className="flex-none transition-transform group-open:rotate-45"
                />
                Read the full disclaimer
              </summary>
              <p className="mt-2 text-caption leading-relaxed text-subtle">
                Each pack is an evidence-backed analysis with cited sources. We don&apos;t guarantee any business outcome. Payments are processed securely by Stripe.
              </p>
            </details>
          </div>

        </div>
      </footer>
    </div>
  );
}
