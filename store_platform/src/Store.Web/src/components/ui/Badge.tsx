import React from 'react';
import { cx } from './cx';
import { Icon, type IconName } from './Icon';

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

/*
 * Brand v3 (2026-08-06). Every tone was `bg-<hue>/10 text-<hue> border-<hue>/20`, i.e. the base
 * hue set on a 10% wash of itself. That is the exact pairing the `-strong` tokens exist to fix:
 * `--danger #DC2626` on `--danger-bg #FEF2F2` measures 4.41:1 and FAILS AA at this size
 * (globals.css:76-86). Each tone now uses the declared `-bg` tint with the `-strong` ink.
 */
const TONES: Record<Tone, string> = {
  neutral: 'border-border bg-surface2 text-muted',
  success: 'border-success/25 bg-success-bg text-success-strong',
  warning: 'border-warning/25 bg-warning-bg text-warning-strong',
  danger: 'border-danger/25 bg-danger-bg text-danger-strong',
  info: 'border-info/25 bg-info-bg text-info',
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
        'inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-0.5 font-mono text-caption',
        TONES[tone],
        className,
      )}
    >
      {icon && <Icon name={icon} size={12} className="-ml-0.5" />}
      {children}
    </span>
  );
}
