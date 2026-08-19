import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { Breadcrumbs } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { CartButton } from '@/components/cart/CartButton';
import { LEGAL, BRAND, traderIdentity } from '@/lib/config';
import { SEARCH_OPEN_EVENT } from '@/lib/searchEvent';
import { RESEARCH_STATS } from '@/lib/stats';
import { tightDecimal } from '@/components/ui/Money';
import { useDisclosure } from '@/lib/useDisclosure';
import { TodayRibbon } from '@/components/marketing/TodayRibbon';

/**
 * High-fidelity shell for the Mumchimp marketing pages. Purely presentational.
 * Standardises the pure-white canvas with the noise grain filter (0.02 opacity).
 *
 * IDENTITY-BLINDNESS: never carries or fetches user identity.
 */

/** The public marketing nav, every entry points at a page that exists. */
export const MARKETING_NAV = [
  // "Catalogue" IS GONE FROM THE NAV, 2026-08-14 (founder, from a screenshot): the wordmark to its
  // immediate left already links to `/`, so the header offered the same destination twice, 90px
  // apart, and the second one spent a nav slot saying what the first one means. A logo that
  // returns home is a convention a reader does not have to be taught; a nav item is not free.
  //
  // The British spelling this comment used to defend still applies wherever the word survives
  // (the footer, /ideas' "Catalogue categories") -- "Catalogue", never "Catalog".
  //
  // Deliberately removed from the LIST rather than filtered at the two render sites: `MARKETING_NAV`
  // feeds both the desktop row (:197) and the mobile sheet (:358), and a filter at one of them is
  // how the two drift apart.
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
 * PREFIX MATCH, EXCEPT FOR `/`. `/ideas/<slug>` has to light up `Collections`, because a landing
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

/* Mirrors BAND_WIDTH in components/marketing/blocks.tsx. Copied rather than imported so the
   shell does not depend on the block library. The trail must sit on the SAME band as the
   page's first Section, otherwise it hangs off the left of the content it belongs to. */
const CRUMB_WIDTH = {
  '2xl': 'max-w-2xl', '3xl': 'max-w-3xl', '4xl': 'max-w-4xl',
  // Both wide keys resolve to the shell's 1080px, exactly as BAND_WIDTH does. The comment above
  // says this map must mirror that one; before 2026-08-18 it mirrored it into the same defect.
  '6xl': 'max-w-[1080px]', '7xl': 'max-w-[1080px]',
} as const;

interface MarketingLayoutProps {
  children: React.ReactNode;
  /** Trail rendered above the page content. Omit on the home page: you cannot go back from it. */
  breadcrumbs?: { href: string; label: string }[];
  /** MUST match the `width` of the page's first Section/SectionBand, so the trail aligns. */
  breadcrumbsWidth?: keyof typeof CRUMB_WIDTH;
}

export default function MarketingLayout({ children, breadcrumbs, breadcrumbsWidth = '3xl' }: MarketingLayoutProps) {
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
  // MASTER-BRIEF section 9: on mobile the header hides on scroll-down and comes back on scroll-up.
  // A phone screen is short and the header is 80px of it. A reader scrolling into the page gets
  // that height back; one scrolling up gets the navigation without first reaching the top.
  const [headerHidden, setHeaderHidden] = useState(false);
  useEffect(() => {
    // One listener, not two. `lastY` is a closure variable rather than state because a re-render
    // per scroll event is the cost this is trying to avoid.
    let lastY = window.scrollY;
    let queued = false;
    // The header sliding away is motion the page plays at the reader, which is what the setting
    // is about, so under prefers-reduced-motion the header simply stays put.
    const reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const read = () => {
      queued = false;
      const y = window.scrollY;
      setScrolled(y > 4);
      // 64px of travel before a direction change counts. Without it, the rubber-band at the top of
      // iOS Safari and one pixel of trackpad jitter both read as a reversal and the header flickers.
      if (!reduced && Math.abs(y - lastY) > 64) {
        setHeaderHidden(y > lastY && y > 160);
        lastY = y;
      }
    };
    const onScroll = () => {
      // Coalesce to one read per frame. `window.scrollY` forces layout, and the raw event fires
      // far more often than the screen refreshes.
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(read);
    };
    read();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // 1080px max, 20px gutters -- `.wrap` in every one of the twelve mockups
  // (docs/design/mumchimp-build-bundle/mockups/*.html: `max-width:1080px;margin:0 auto;padding:0
  // 20px`). It was 1200/24, from §3.4, which itself replaced `max-w-7xl px-4 sm:px-6 lg:px-8` --
  // 1280px with a gutter that stepped 16 -> 24 -> 32px across breakpoints.
  //
  // The step was the problem then and it is still fixed: ONE gutter value at every width, so the
  // grid's outer margin is somewhere a component can align to. What changed on 2026-08-18 is the
  // number. 120px of extra width is not a detail at this scale -- every row, card grid and measure
  // on the site was laid out 11% wider than the drawing, so nothing inside them could line up with
  // the mockup even where the component itself was right.
  const SHELL = 'mx-auto max-w-[1080px] px-5';

  return (
    <div className="min-h-dvh bg-bg font-sans text-text antialiased">
      <a
        href="#main"
        /* The drawing's `.skip` (`mockups/index.html:264`): parked off-screen, and drawn as a
           dark chip at the top left the moment it takes focus. Ten focus-visible utilities said
           the same thing by hand. */
        className="skip"
      >
        Skip to content
      </a>

      {/* The drawing puts the dark strip ABOVE the header on all eleven pages, and it scrolls
          away rather than sticking. See `TodayRibbon` for why the tag prints a date. */}
      <TodayRibbon />

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
      {/* THE DRAWING'S HEADER, copied from `mockups/*.html` <header class="hdr">.

          It emits the drawing's own class names, which `src/styles/mumchimp.css` styles. That file
          is the drawings' stylesheet copied byte-for-byte, so the header is the drawing rather
          than a translation of it: 58px tall, a 1080px wrap on a 20px gutter, the wordmark on the
          left with `margin-right:auto`, the nav and the account link hidden below 920px.

          Two things the drawing cannot show, both kept: the cart button, which renders nothing
          until there is something in it, and the hide-on-scroll transform below.  */}
      <header
        data-scrolled={scrolled ? 'true' : 'false'}
        className={cx(
          'hdr transition-transform duration-200',
          /* PHONE ONLY. `md:!translate-y-0` is the whole point: on a desktop viewport the header
             costs a small fraction of the screen, so moving it buys nothing and costs the reader
             their bearings. Classes, not an inline transform -- an inline style has no
             breakpoint, so it hid the desktop header too. */
          headerHidden ? '-translate-y-full md:!translate-y-0' : 'translate-y-0',
        )}
        style={{ borderBottomColor: scrolled ? 'var(--line-2)' : 'var(--line)' }}
      >
        <div className="hdr-in">
          <Link className="logo" href="/" aria-label={`${BRAND.name} home`}>
            <svg width="26" height="24" viewBox="0 0 26 24" fill="none" aria-hidden="true">
              <path d="M1 2h24l-4.1 5H5.1L1 2Z" fill="#14706A" />
              <path d="M6.2 9.5h13.6l-3.3 5H9.5l-3.3-5Z" fill="#14706A" />
              <path d="M10.7 17h4.6L13 22.5 10.7 17Z" fill="#14706A" />
            </svg>
            <span className="wordmark">
              <b>Mum</b>chimp
            </span>
          </Link>
          <nav className="nav-d">
            {MARKETING_NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActivePath(router.pathname, item.href) ? 'page' : undefined}
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <Link className="acct" href="/account">
            Account
          </Link>
          {/* Renders nothing until there is something in it, see CartButton. */}
          <CartButton />
          {/* "Search the catalogue", not "Search". Below 980px `mumchimp.css:436` sets
              `.fb-in{display:none}`, so the shelf toolbar's own trigger is not rendered on a
              phone and THIS button is the only search control the reader has -- which is the job
              the docblock above hands it. The name is what `e2e/discovery.spec.ts:254,266` scopes
              to `header` to prove that both dispatch paths work, and the redraw renamed it to the
              bare verb, so those two tests have been failing on live since 2026-08-19. A specific
              accessible name is also the better one: "Search" alone tells a screen-reader user
              nothing about what is being searched. Invisible to the drawing -- `parity.mjs` drops
              aria-label, and the button renders an icon, not this text. */}
          <button type="button" className="icon-btn" aria-label="Search the catalogue" onClick={openSearch}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <circle cx="9" cy="9" r="6.25" stroke="currentColor" strokeWidth="1.7" />
              <path d="m13.8 13.8 4 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </button>
          <button
            type="button"
            ref={menuButtonRef}
            /* `menu`, not decoration: mumchimp.css:431 is
               `@media(min-width:921px){.icon-btn.menu{display:none}}`, so without this class the
               hamburger renders beside the desktop nav at every width. Measured 2026-08-18 against
               `mockups/index.html`, which carries `class="icon-btn menu"`. */
            className="icon-btn menu"
            aria-label="Menu"
            aria-expanded={menuOpen}
            aria-controls="site-menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M2.5 5.5h15M2.5 10h15M2.5 14.5h15" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        {/* The drawings are static pages, so none of them draws the open menu. It reuses the
            footer column's link styling, which is the same list at the same size. */}
        {menuOpen && (
          <div id="site-menu" className="wrap" style={{ borderTop: '1px solid var(--line)', padding: '14px 20px 18px' }}>
            <nav aria-label="Marketing" className="f-col">
              {MARKETING_NAV.map((item) => (
                <Link key={item.href} href={item.href} onClick={() => setMenuOpen(false)}>
                  {item.label}
                </Link>
              ))}
              <Link href="/account" onClick={() => setMenuOpen(false)}>
                Account
              </Link>
            </nav>
          </div>
        )}
      </header>

      {/* Full-width main: children own their contrast bands. */}
      <main id="main" className="bg-bg">
        {/* `px-5 pt-[22px]` on the trail below: the drawing's gutter and the drawing's trail
            offset (`mockups/sample.html:64`, `.crumb{padding:22px 0 0}`). The three-step gutter it
            replaces put the trail 40px from the page edge on a laptop, under a header sitting at
            20px. The note is here rather than inside the conditional because a JSX comment there
            would be a second child of the `&&` expression. The `pt-[22px]` that used to sit on
            this wrapper is gone: `.crumb` on the trail itself carries `padding:22px 0 0`, and
            keeping both paid it twice. */}
        {breadcrumbs && breadcrumbs.length > 0 && (
          <div className={`mx-auto ${CRUMB_WIDTH[breadcrumbsWidth]} px-5`}>
            <Breadcrumbs items={breadcrumbs} />
          </div>
        )}
        {children}
      </main>

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
      {/* THE DRAWING'S FOOTER, copied from `mockups/*.html` <footer>. Four columns at 1.4fr 1fr
          1fr 1fr, dropping to two at 860px and one at 520px, all of it from the copied stylesheet.

          The column headings are `<p class="colh">`, copied from the bundle's own footer. The
          older drawing wrote `<h6>` and we drew an `<h2>` instead, because the footer renders
          after every page's `<h1>` and an `<h6>` there skips four levels and trips axe's
          `heading-order`. The bundle settled it: `mumchimp.css:393` styles `.f-col .colh`, so the
          heading look no longer needs a heading element, and the local `.f-col h2` copy in
          globals.css is gone with it. */}
      <footer>
        <div className="wrap">
          <div className="f-top">
            <div className="f-brand">
              <Link className="logo" href="/" aria-label={`${BRAND.name} home`}>
            <svg width="26" height="24" viewBox="0 0 26 24" fill="none" aria-hidden="true">
              <path d="M1 2h24l-4.1 5H5.1L1 2Z" fill="#14706A" />
              <path d="M6.2 9.5h13.6l-3.3 5H9.5l-3.3-5Z" fill="#14706A" />
              <path d="M10.7 17h4.6L13 22.5 10.7 17Z" fill="#14706A" />
            </svg>
                <span className="wordmark" style={{ fontSize: '19px' }}>
                  <b>Mum</b>chimp
                </span>
              </Link>
              <p>Business ideas that survived the filter. Fully sourced, ready to build.</p>
              {/* `tightDecimal` on both figures: they are the two biggest numbers on the page and
                  the decimal comma sets loose at this weight. */}
              <div className="f-stats">
                <div>
                  <span>Killed</span>
                  <b className="num whitespace-nowrap">{tightDecimal(RESEARCH_STATS.killed.toLocaleString('en-GB'))}</b>
                </div>
                <div>
                  <span>Researched</span>
                  <b className="num whitespace-nowrap">{tightDecimal(RESEARCH_STATS.researched.toLocaleString('en-GB'))}</b>
                </div>
              </div>
            </div>
            <div className="f-col">
              <p className="colh">Store</p>
              <Link href="/">Catalogue</Link>
              <Link href="/ideas">Categories</Link>
              <Link href="/how-it-works">How it works</Link>
              <Link href="/kill-log" prefetch={false}>Kill log</Link>
              <Link href="/about">Who makes this</Link>
              <Link href="/faq">FAQ</Link>
            </div>
            <div className="f-col">
              <p className="colh">Legal</p>
              <Link href="/terms">Terms of Service</Link>
              <Link href="/privacy">Privacy Policy</Link>
              <Link href="/refund">Refund Policy</Link>
            </div>
            <div className="f-col">
              <p className="colh">Contact</p>
              <a href={`mailto:${LEGAL.supportEmail}`}>{LEGAL.supportEmail}</a>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '14px' }}>
                <Link className="btn sm" href="/">
                  Browse
                </Link>
                <Link className="tlink" href="/kill-log" prefetch={false} style={{ alignSelf: 'center' }}>
                  See what we killed
                </Link>
              </div>
            </div>
          </div>
          <div className="f-bottom">
            <p>
              &copy; 2026 {BRAND.name}. All rights reserved. {BRAND.name} packs are sold for
              information only, not financial, legal, or investment advice.
            </p>
            <p>
              {/* The trader, named on the shop front rather than three clicks into the legal
                  pages. reg 6 of the E-Commerce Regulations 2002 says "easily, directly and
                  permanently accessible", and a footer is the only surface on this site that is
                  all three. Baymard's abandonment list puts "didn't trust the site" at 19% of
                  abandoners, and an anonymous seller asking for 99.99 is that finding. */}
              Operated by {traderIdentity()}.
            </p>
            <details>
              <summary>Read the full disclaimer</summary>
              <p style={{ marginTop: '8px' }}>
                Each pack is an evidence-backed analysis with cited sources. We do not guarantee any
                business outcome. Payments are processed securely by Stripe.
              </p>
            </details>
          </div>
        </div>
      </footer>
    </div>
  );
}
