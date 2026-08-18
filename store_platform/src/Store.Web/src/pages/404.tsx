import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';

/**
 * 404, drawn from `docs/design/mumchimp-build-bundle/mockups/404.html`.
 *
 * It emits the drawing's own class names (`.wrap`, `.err`, `.code`, `.lede`, `.ctarow`, `.btn`),
 * which `src/styles/mockup.css` styles. That file is the drawings' stylesheet copied
 * byte-for-byte, so this page is the drawing rather than a translation of it.
 *
 * TWO BUTTONS, as the drawing has. It carried one for a while, on a rule that an error page names
 * what happened and offers the single route that fixes it. The drawing offers the shelf and the
 * kill log, and the kill log is the page that explains why a pack someone had a link to may no
 * longer exist, so the second button answers the question the first one leaves open.
 */
export default function NotFound() {
  return (
    <MarketingLayout>
      <Seo title="Page not found" noindex />
      <div className="wrap">
        <div className="err">
          <p className="code num">404</p>
          <h1>That page isn&apos;t here.</h1>
          <p className="lede" style={{ maxWidth: '46ch' }}>
            It may have been renamed, or the idea behind it was killed before it ever shipped.
            Every pack we have published is on the shelf, and it is searchable.
          </p>
          <div className="ctarow" style={{ justifyContent: 'center' }}>
            <Link className="btn" href="/">
              Browse the catalogue
            </Link>
            <Link className="btn ghost" href="/kill-log">
              Read the kill log
            </Link>
          </div>
        </div>
      </div>
    </MarketingLayout>
  );
}
