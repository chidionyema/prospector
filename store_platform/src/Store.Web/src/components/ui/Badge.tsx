import React from 'react';
import { cx } from './cx';
import { Icon, type IconName } from './Icon';

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

const TONES: Record<Tone, string> = {
  neutral: 'bg-bg text-text/80 border border-border',
  success: 'bg-success/10 text-success border border-success/20 shadow-sm',
  warning: 'bg-warning/10 text-warning border border-warning/20 shadow-sm',
  danger: 'bg-danger/10 text-danger border border-danger/20 shadow-sm',
  info: 'bg-info/10 text-info border border-info/20 shadow-sm',
};

export interface BadgeProps {
  tone?: Tone;
  /** Optional leading status glyph (inherits the tone colour). */
  icon?: IconName;
  children: React.ReactNode;
  className?: string;
}

/** Small status pill. Tone is semantic, never raw color (UI-STANDARDS §2). */
export function Badge({ tone = 'neutral', icon, children, className }: BadgeProps) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-md px-2.5 py-0.5 text-[11px] font-mono font-bold uppercase tracking-wider',
        TONES[tone],
        className,
      )}
    >
      {icon && <Icon name={icon} size={12} className="-ml-0.5" />}
      {children}
    </span>
  );
}
