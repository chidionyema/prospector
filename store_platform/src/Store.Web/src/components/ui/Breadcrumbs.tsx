import Link from 'next/link';

export function Breadcrumbs({ items }: { items: { href: string; label: string }[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-x-1.5 text-sm">
        {items.map((item, i) => {
          const isLast = i === items.length - 1;
          return (
            <li key={i} className="flex items-center gap-x-1.5">
              {isLast ? (
                <span aria-current="page" className="font-semibold text-text">
                  {item.label}
                </span>
              ) : (
                <Link href={item.href} className="text-muted hover:text-text transition-colors">
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
