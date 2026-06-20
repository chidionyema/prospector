import { Html, Head, Main, NextScript } from "next/document";
import { SITE_URL, BRAND } from "@/lib/config";

// E30-002 (WR-037): site-wide JSON-LD — Organization + WebSite. Helps search engines understand the
// brand as an entity (knowledge-panel eligibility) without claiming anything we can't substantiate:
// no aggregateRating / Review / Offer availability (zero-fabricated-proof guardrail). Gated on
// SITE_URL exactly like the canonical tag — absolute URLs only emit in a configured (prod) build,
// and crawlers only see the production origin anyway.
//
// Rendered as a text-child <script> (NOT dangerouslySetInnerHTML, which the react/no-danger rail
// bans). That means the serialized JSON must contain no `&`, `<`, or `>` — inside a raw-text <script>
// element those would survive as literal entity text and corrupt the JSON. The values below are plain
// ASCII (apostrophes are fine), so this is safe; keep it that way if you edit the description.
const SITE = BRAND.name;
const ORG_DESCRIPTION =
  "Prospector Store sells grounded business opportunity packs. Each is a vetted idea with a " +
  "Blueprint, GTM plan, and Build Kit, sourced and ready to build.";

const siteJsonLd = SITE_URL
  ? JSON.stringify({
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": "Organization",
          "@id": `${SITE_URL}/#organization`,
          name: SITE,
          url: SITE_URL,
          logo: `${SITE_URL}/icon.svg`,
          description: ORG_DESCRIPTION,
        },
        {
          "@type": "WebSite",
          "@id": `${SITE_URL}/#website`,
          name: SITE,
          url: SITE_URL,
          publisher: { "@id": `${SITE_URL}/#organization` },
        },
      ],
    })
  : null;

export default function Document() {
  return (
    <Html lang="en">
      <Head>
        {/* Brand chrome (BRAND-AND-DESIGN §4/§9). SVG favicon for modern browsers; the legacy
            .ico is the fallback. theme-color paints the mobile browser bar in brand ink. */}
        <link rel="icon" href="/icon.svg" type="image/svg+xml" />
        <link rel="alternate icon" href="/favicon.ico" sizes="any" />
        <link rel="apple-touch-icon" href="/icon.svg" />
        <meta name="theme-color" content="#0f172a" />
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
