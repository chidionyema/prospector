import React from 'react';
import Link from 'next/link';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { FOUNDER, hasFounder } from '@/lib/config';

/**
 * The one human on the site.
 *
 * Renders NOTHING until `FOUNDER.name` is set (see the block on it in `lib/config.ts`). That is
 * the whole safety property: the founder's identity is a claim about a real person, and this
 * component will not invent one, imply one, or hold space for one. An unfilled config is an
 * absence, never a placeholder -- no grey silhouette, no "founder photo coming soon", nothing that
 * looks like a broken promise on a page arguing that its promises are checkable.
 *
 * Two variants, because the two places that want a founder want different amounts of them:
 *  - `compact` (home page): a name, a line, and a link out. It exists to prove a person exists.
 *  - `full` (/about): the same plus the bio, where a reader who came looking has room to read.
 */
export function FounderNote({
  variant = 'compact',
  className,
}: {
  variant?: 'compact' | 'full';
  className?: string;
}) {
  if (!hasFounder()) return null;

  const full = variant === 'full';

  return (
    <aside
      className={cx(
        'flex flex-col gap-4 rounded-md border border-border bg-surface p-6 sm:flex-row sm:items-start sm:gap-5',
        full && 'md:p-8',
        className,
      )}
    >
      {/* Plain <img>, not next/image: this is one small, static, self-hosted portrait, and it is
          optional. Wiring it through the image optimiser buys nothing and adds a way for the one
          human element on the site to fail to render. */}
      {FOUNDER.photo && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={FOUNDER.photo}
          alt={FOUNDER.name}
          className={cx(
            'h-16 w-16 flex-none rounded-full object-cover',
            full && 'md:h-20 md:w-20',
          )}
        />
      )}
      <div className="min-w-0">
        <p className="text-body font-semibold text-text">{FOUNDER.name}</p>
        {FOUNDER.role && <p className="mt-0.5 text-meta text-muted">{FOUNDER.role}</p>}
        {full && FOUNDER.bio && (
          <p className="mt-3 max-w-[60ch] text-body leading-relaxed text-muted">{FOUNDER.bio}</p>
        )}
        {!full && FOUNDER.bio && (
          /* One line on the home page. `line-clamp-2` rather than a separate short-bio field:
             a second field is a second thing to keep true, and the founder would have to write
             the same thing twice. */
          <p className="mt-2 line-clamp-2 max-w-[60ch] text-meta leading-relaxed text-muted">
            {FOUNDER.bio}
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2">
          {FOUNDER.profileUrl && (
            <a
              href={FOUNDER.profileUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
            >
              <Icon name="arrowRight" size={12} className="-rotate-45 shrink-0" />
              Check who I am
            </a>
          )}
          {!full && (
            <Link
              href="/about"
              className="inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
            >
              Why this shop exists
              <Icon name="arrowRight" size={14} />
            </Link>
          )}
        </div>
      </div>
    </aside>
  );
}

export default FounderNote;
