import React from 'react';
import { cx } from './cx';

export interface DescriptionItem {
  term: React.ReactNode;
  description: React.ReactNode;
}

export interface DescriptionListProps {
  items: DescriptionItem[];
  className?: string;
}

/**
 * A proper key to value description list — term muted on the left, value on the right, hairline rows.
 * Replaces the stacked `<p>label</p><p>value</p>` blocks that made settings read like a config dump
 * (SITE-POLISH-SPEC §2.5).
 */
export function DescriptionList({ items, className }: DescriptionListProps) {
  return (
    <dl className={cx('divide-y divide-border', className)}>
      {items.map((item, i) => (
        <div key={i} className="flex flex-col gap-1 py-3 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6">
          <dt className="text-small text-muted">{item.term}</dt>
          <dd className="text-small text-text sm:text-right">{item.description}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface ListRowProps {
  /** Leading slot — an icon, avatar, or status dot. */
  leading?: React.ReactNode;
  title: React.ReactNode;
  /** Secondary line under the title. */
  meta?: React.ReactNode;
  /** Trailing slot — an action, badge, or value. */
  trailing?: React.ReactNode;
  className?: string;
}

/**
 * One row of a real list: leading · (title + meta) · trailing. Compose inside a Card with
 * `divide-y divide-border` for connected accounts / roster, instead of a raw `<ul divide-y>` that read
 * like a webhook console (SITE-POLISH-SPEC §2.5).
 */
export function ListRow({ leading, title, meta, trailing, className }: ListRowProps) {
  return (
    <div className={cx('flex items-center gap-4 py-3', className)}>
      {leading && <div className="shrink-0">{leading}</div>}
      <div className="min-w-0 flex-1">
        <div className="truncate text-small font-semibold text-text">{title}</div>
        {meta && <div className="truncate text-caption text-muted">{meta}</div>}
      </div>
      {trailing && <div className="shrink-0">{trailing}</div>}
    </div>
  );
}
