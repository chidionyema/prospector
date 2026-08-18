import Link from 'next/link';

export function Breadcrumbs({ items }: { items: { href: string; label: string }[] }) {
  return (
    /* THE DRAWING'S `.crumb` (`mockups/about.html:281`: mono, 12.5px, --ink-3, 22px of padding
       above it, links in --link). It was `text-meta` on the list and `text-muted` on each link,
       which is the same line said in utilities, so no page on the site emitted the class the
       mockups style. The utilities that set colour and size are REMOVED rather than layered:
       mumchimp.css is imported into `layer(components)` (globals.css:8) and Tailwind utilities sit
       above it, so a utility left in place beats the class and the change would be a no-op. */
    <nav aria-label="Breadcrumb" className="crumb">
      <ol className="flex flex-wrap items-center gap-x-1.5">
        {items.map((item, i) => {
          const isLast = i === items.length - 1;
          return (
            <li key={i} className="flex items-center gap-x-1.5">
              {isLast ? (
                /* Capped and clipped. Pack titles run past 100 characters ("StorySprout, the custom
                   printed social story book that helps your autistic child navigate a new
                   situation, made from your own details"), and the trail rendered the whole thing,
                   so the breadcrumb became the widest line on the page and pushed the real content
                   down. The full text stays available to assistive tech via `title`. */
                <span
                  aria-current="page"
                  title={item.label}
                  className="block max-w-[24ch] truncate font-semibold text-text sm:max-w-[40ch]"
                >
                  {item.label}
                </span>
              ) : (
                <Link href={item.href} className="inline-block py-3">
                  {item.label}
                </Link>
              )}
              {!isLast && <span aria-hidden className="text-muted">/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
