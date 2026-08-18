import React from 'react';
import { cx } from './cx';
import { Icon } from './Icon';
import { Money } from './Money';

export interface MoneyHeroProps {
  /** Amount in MINOR units, straight from the API. */
  cents: number;
  currency: string;
  /** Bounty/escrow state, drives the held vs released framing + which wash earns its place. */
  state: string;
  /** Override the auto status label (defaults from state). */
  label?: string;
  /** A short line under the figure (e.g. who is holding it, what unlocks it). */
  caption?: React.ReactNode;
  /** Optional right-aligned action. */
  action?: React.ReactNode;
  className?: string;
}

const HELD_STATES = ['EscrowLocked', 'BridgeActive', 'Disputed', 'PendingMatch'];

/**
 * The escrow figure as the hero of a surface, the largest, most confident thing on the dashboard and
 * the bounty detail. Everything else on the page recedes beneath it (SITE-POLISH-SPEC §2.3). For a
 * compact inline figure use MoneyBand instead.
 *
 * Brand v3 (2026-08-06). This carried `bg-vault-wash` / `bg-settled-wash` / `text-gold`: three
 * tokens deleted with the v2 palette (`--gold` was an alias of `--success`; globals.css:104). In
 * Tailwind v4 an unmapped utility emits NO rule, so the "earned flourish" this comment described
 * had in fact been rendering as a plain white box with black status text for as long as the
 * tokens have been gone. The state signal now runs through the semantic pair that survives:
 * `--success` for released, neutral ink for everything else.
 */
export function MoneyHero({ cents, currency, state, label, caption, action, className }: MoneyHeroProps) {
  const isReleased = state === 'AutoSettled';
  const isRefunded = state === 'Refunded';
  const isHeld = HELD_STATES.includes(state);

  const statusLabel =
    label ??
    (isReleased
      ? 'Settled and released'
      : isRefunded
        ? 'Returned to your bank'
        : isHeld
          ? 'Held by your bank'
          : state);

  return (
    <div
      className={cx(
        'relative overflow-hidden rounded-card border border-border bg-surface p-6 sm:p-8',
        isReleased && 'border-l-2 border-l-success',
        className,
      )}
    >
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1.5">
          <div
            className={cx(
              'flex items-center gap-2 text-caption font-medium',
              isReleased ? 'text-success' : 'text-subtle',
            )}
          >
            <Icon
              name={isReleased ? 'released' : 'held'}
              size={16}
              className={isReleased ? 'text-success' : 'text-subtle'}
            />
            <span>{statusLabel}</span>
          </div>
          <Money cents={cents} currency={currency} className="block text-h1 text-text" />
          {caption && <p className="max-w-[60ch] lede">{caption}</p>}
        </div>
        {action && <div className="shrink-0 sm:pb-1">{action}</div>}
      </div>
    </div>
  );
}
