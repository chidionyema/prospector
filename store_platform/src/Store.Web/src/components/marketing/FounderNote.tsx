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
 * It does NOT carry the founder's story. `FOUNDER.bio` used to exist and used to be rendered here
 * in two lengths -- the full paragraph on /about, the same paragraph `line-clamp-2`'d on the home
 * page -- which is how a stranger met the same person twice. /about owns the story now (see the
 * block where `bio` used to be in `lib/config.ts`, and `factOwnership.test.ts`), so this component
 * names the person and points at it.
 *
 * Two variants, because the two places that want a founder want different amounts of them:
 *  - `compact`: name, role, and the link to /about. It exists to prove a person exists.
 *  - `full` (/about): the same, larger, WITHOUT the link -- you are already on the page it goes to.
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
