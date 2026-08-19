import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { PackRowList } from '@/components/discovery/PackRow';
import { Icon } from '@/components/ui';
import { fetchCatalog, type Pack } from '@/lib/api/client';

/**
 * 404, drawn from `docs/design/mumchimp-build-bundle/mockups/404.html`.
 *
 * It emits the drawing's own class names (`.wrap`, `.err`, `.code`, `.lede`, `.ctarow`, `.btn`),
 * which `src/styles/mumchimp.css` styles. That file is the drawings' stylesheet copied
 * byte-for-byte, so this page is the drawing rather than a translation of it.
 *
 * TWO BUTTONS, as the drawing has. It carried one for a while, on a rule that an error page names
 * what happened and offers the single route that fixes it. The drawing offers the shelf and the
 * kill log, and the kill log is the page that explains why a pack someone had a link to may no
 * longer exist, so the second button answers the question the first one leaves open.
 *
 * The drawing also carries a "While you're here" panel below the buttons with one pack in it,
 * drawn as the same `.row` every shelf uses. It is fetched on the client because 404 is a static
 * page, and it is silent on failure: a reader who mistyped a URL does not need to be told the
 * catalogue is down as well.
 */
export default function NotFound() {
  const [suggestion, setSuggestion] = React.useState<Pack | null>(null);

  React.useEffect(() => {
    let live = true;
    fetchCatalog()
      .then((packs) => {
        if (live && packs.length > 0) setSuggestion(packs[0]);
      })
      .catch(() => {
        // Silent on purpose, see the note above.
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <MarketingLayout>
      <Seo title="Page not found" noindex />
      <div className="wrap">
        <div className="err">
          <p className="code num">404</p>
          <h1>That page isn&apos;t here.</h1>
          <p className="lede" style={{ maxWidth: '46ch' }}>
            It may have been renamed, or the idea behind it was killed before it ever shipped.
            Every pack we have published is available now, and it is searchable.
          </p>
          <div className="ctarow" style={{ justifyContent: 'center' }}>
            <Link className="btn" href="/">
              Browse the catalogue <Icon name="arrowRight" size={16} />
            </Link>
            <Link className="btn ghost" href="/kill-log" prefetch={false}>
              Read the kill log
            </Link>
          </div>
        </div>

        {suggestion && (
          <div className="sigcard mx-auto max-w-[560px]">
            <p className="eyebrow mb-3">While you&apos;re here</p>
            {/* The drawing drops the list's own border inside the panel, so the panel is the only
                box. `.rows` sets its border in the components layer; a utility beats it. */}
            <PackRowList packs={[suggestion]} className="border-0" />
          </div>
        )}
      </div>
    </MarketingLayout>
  );
}
