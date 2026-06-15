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
 * The escrow figure as the hero of a surface — the largest, most confident thing on the dashboard and
 * the bounty detail. The one place the "earned flourish" lands: a faint band-tinted vault wash for held
 * money, a brass wash for settled money (gold = settled-money signal only). Everything else on the page
 * recedes beneath it (SITE-POLISH-SPEC §2.3). For a compact inline figure use MoneyBand instead.
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
        'relative overflow-hidden rounded-lg border border-border p-6 shadow-vault sm:p-8',
        isReleased ? 'bg-settled-wash' : 'bg-vault-wash',
        className,
      )}
    >
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <div
            className={cx(
              'flex items-center gap-2 text-caption font-semibold uppercase tracking-[0.14em]',
              isReleased ? 'text-gold' : 'text-muted',
            )}
          >
            <Icon
              name={isReleased ? 'released' : 'held'}
              size={16}
              className={isReleased ? 'text-gold' : 'text-muted'}
            />
            <span>{statusLabel}</span>
          </div>
          <Money cents={cents} currency={currency} className="block text-hero text-text" />
          {caption && <p className="max-w-md text-small text-muted">{caption}</p>}
        </div>
        {action && <div className="shrink-0 sm:pb-1">{action}</div>}
      </div>
    </div>
  );
}
