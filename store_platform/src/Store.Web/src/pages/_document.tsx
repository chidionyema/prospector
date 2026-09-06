import { Html, Head, Main, NextScript } from "next/document";
import { graph, organizationNode, webSiteNode } from "@/lib/seo/schema";
import { SEARCH_ENGINE_VERIFICATIONS } from "@/lib/seo/verification";

// E30-002 (WR-037): site-wide JSON-LD, Organization + WebSite. Helps search engines understand the
// brand as an entity (knowledge-panel eligibility) without claiming anything we can't substantiate:
// no aggregateRating / Review / Offer availability (zero-fabricated-proof guardrail). Gated on
// SITE_URL exactly like the canonical tag, absolute URLs only emit in a configured (prod) build,
// and crawlers only see the production origin anyway.
//
// The node shapes moved to `lib/seo/schema.ts` so that per-page structured data can reference this
// Organization by `@id` instead of describing a second, unrelated brand entity. This file still
// owns *where* the site-wide graph renders (once, on every page, from the document head).
//
// Rendered as a text-child <script> (NOT dangerouslySetInnerHTML, which the react/no-danger rail
// bans). That means the serialized JSON must contain no `&`, `<`, or `>`, inside a raw-text <script>
// element those would survive as literal entity text and corrupt the JSON. The builders emit plain
// ASCII (apostrophes are fine); the assertion below is what stops that invariant rotting silently.
const ORG_DESCRIPTION =
  "Mumchimp sells sourced business opportunity packs. Each is a vetted idea with a " +
  "build spec, a plan for your first customers and the numbers behind both. Every claim carries a source.";

const siteGraph = graph(organizationNode(ORG_DESCRIPTION), webSiteNode());
const serialized = siteGraph ? JSON.stringify(siteGraph) : null;

// A raw-text <script> cannot carry these three characters (see above). Rather than trust a comment
// to survive future edits, drop the block if the invariant is ever broken: no structured data is a
// missed opportunity, but corrupted structured data is a parse error on every page of the site.
// `lib/seo/__tests__/schema.test.ts` asserts the payload is clean, so this should never fire.
const siteJsonLd = serialized && !/[&<>]/.test(serialized) ? serialized : null;

export default function Document() {
  return (
    <Html lang="en">
      <Head>
        {/* Brand chrome (BRAND-AND-DESIGN §4/§9). SVG favicon for modern browsers; the legacy
            .ico is the fallback. theme-color paints the mobile browser bar in brand ink. */}
        <link rel="preconnect" href="https://api.stripe.com" />
        <link rel="preconnect" href="https://js.stripe.com" />
        <link rel="icon" href="/icon.svg" type="image/svg+xml" />
        <link rel="alternate icon" href="/favicon.ico" sizes="any" />
        {/* NO apple-touch-icon here, deliberately (removed 2026-08-14). This file declared
            `rel="apple-touch-icon" href="/icon.svg"` while `components/Seo.tsx` declared the same
            rel pointing at `/apple-touch-icon.png`, and both shipped: _document's <Head> and the
            page's <Head> are separate trees, so next/head's `key` dedupe cannot see across them
            (the theme-color comment below turns on exactly that fact). iOS does not support SVG
            for a home-screen tile at all, so the declaration here was inert at best and, being
            first in tree order, a coin-flip at worst. One declaration, in Seo.tsx, pointing at a
            real PNG. */}
        {/* theme-color must be the PAGE GROUND, not the ink (MASTER-BRIEF §9, corrected
            2026-08-17). It was `#171717`, the text colour, which painted a near-black browser bar
            above a paper-white page: on a phone the chrome and the page read as two different
            sites, and in an in-app browser the seam is the first thing a buyer sees. The value is
            `--paper`. Raw hex is required here because a <meta> content attribute is not a CSS
            context and cannot resolve var().
            This declaration is the one browsers use: _document's <Head> renders before the page's,
            and the first theme-color wins -- so editing only components/Seo.tsx changes nothing. */}
        <meta name="theme-color" content="#F9F8F6" />
        {/* The other half of the same requirement (MASTER-BRIEF §9: "declares `color-scheme: light
            only` in <meta> AND CSS"). globals.css carries the CSS half. Both, because they are
            read at different moments: the meta tag is in the document head before any stylesheet
            has loaded, which is the window an in-app browser or Android auto-dark uses to decide
            it may invert the page. `only` rather than `light` is the load-bearing word -- plain
            `light` still leaves forced-dark permitted, and a forced-dark render turns the teal
            muddy on exactly the surface the brand is identified by. */}
        <meta name="color-scheme" content="light only" />
        {/* Search-console ownership tokens. Empty until the operator sets the env vars, which is
            why they are data-driven rather than pasted here: a token is per-property, and a wrong
            one silently fails verification. See `lib/seo/verification.ts`. */}
        {SEARCH_ENGINE_VERIFICATIONS.map(({ name, content }) => (
          <meta key={name} name={name} content={content} />
        ))}
        {siteJsonLd && (
          <script type="application/ld+json">{siteJsonLd}</script>
        )}
      </Head>
      <body className="antialiased">
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
