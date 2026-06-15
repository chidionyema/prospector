import React from 'react';
import { cx } from './cx';
import { Icon, type IconName } from './Icon';

export interface StatCardProps {
  label: string;
  value: React.ReactNode;
  /** Optional small line under the value. */
  sub?: React.ReactNode;
  icon?: IconName;
  className?: string;
}

/** A quiet secondary number — active intros, pending offers. Tabular, calm, no chartjunk; it sits
 *  beside (never competes with) the MoneyHero (SITE-POLISH-SPEC §2.3). */
export function StatCard({ label, value, sub, icon, className }: StatCardProps) {
  return (
    <div className={cx('rounded-lg border border-border bg-surface p-5', className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-caption font-semibold uppercase tracking-wider text-muted">{label}</p>
        {icon && <Icon name={icon} size={16} className="text-faint" />}
      </div>
      <p className="mt-2 text-display font-semibold tabular-nums text-text">{value}</p>
      {sub && <p className="mt-1 text-caption text-muted">{sub}</p>}
    </div>
  );
}
