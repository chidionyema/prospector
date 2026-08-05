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
  "Mumchimp sells grounded business opportunity packs. Each is a vetted idea with a " +
  "build spec, a GTM plan, operations and unit economics, and a sourced QA report.";

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
        <link rel="apple-touch-icon" href="/icon.svg" />
        <meta name="theme-color" content="#0A0A0A" />
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
