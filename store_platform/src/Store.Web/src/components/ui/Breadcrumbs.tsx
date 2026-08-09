import Link from 'next/link';

export function Breadcrumbs({ items }: { items: { href: string; label: string }[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-x-1.5 text-meta">
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
                <Link href={item.href} className="inline-block py-3 text-muted hover:text-text transition-colors">
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
