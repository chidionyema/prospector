import React from 'react';
import { cx } from './cx';

export interface SkeletonProps {
  className?: string;
}

/** Loading placeholder. Respects prefers-reduced-motion via the global animation opt-out. */
export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cx('animate-pulse rounded-md bg-border/60', className)}
    />
  );
}
