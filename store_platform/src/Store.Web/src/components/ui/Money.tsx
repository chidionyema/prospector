import React from 'react';
import { cx } from './cx';

export interface MoneyProps {
  /** Amount in MINOR units (e.g. `escrow_amount_cents`). This component never does math beyond /100. */
  cents: number;
  /** ISO 4217 code, e.g. `USD`, `GBP`, `EUR`. Comes straight from the API field. */
  currency: string;
  className?: string;
}

/**
 * Renders a minor-unit money amount. The ONLY way money is shown (UI-STANDARDS §2).
 * Fixed locale so server and client render byte-identical (no hydration drift).
 */
export function Money({ cents, currency, className }: MoneyProps) {
  const formatted = new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency,
  }).format(cents / 100);
  return <span className={cx('font-mono font-semibold tabular-nums', className)}>{formatted}</span>;
}
