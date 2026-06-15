import React, { useRef } from 'react';
import { useMode, type Mode } from '@/context/ModeContext';
import { cx, useToast } from '@/components/ui';
import { BRAND } from '@/lib/config';

/**
 * WR-036 (Model C): the always-visible role switch. One account, exactly one active role at a time.
 * A two-segment control (not a hidden menu) so the active mode is unambiguous AND the other mode stays
 * discoverable. The single biggest fill-rate lever is the well-connected person who joined to fund an
 * intro noticing they can also earn one. Switching only changes which surface we emphasise; the server
 * enforces ownership and the self-dealing block regardless of mode.
 */
const OPTIONS: { value: Mode; label: string }[] = [
  { value: 'seeker', label: 'Seeker Mode' },
  { value: 'connector', label: 'Connector Mode' },
];

export default function ModeToggle({ fullWidth = false }: { fullWidth?: boolean }) {
  const { mode, setMode } = useMode();
  const { toast } = useToast();
  const btnRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const handleToggle = (next: Mode) => {
    if (next === mode) return;
    setMode(next);
    toast(
      `Viewing as ${next === 'seeker' ? 'Seeker' : 'Connector'}. Your navigation has been updated.`,
      'info'
    );
  };

  // ARIA radiogroup keyboard pattern: arrows move selection AND focus (with wrap); only the checked
  // radio sits in the tab order (roving tabindex), so Tab enters/leaves the group as one stop.
  function onKeyDown(e: React.KeyboardEvent, index: number) {
    let next: number | null = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (index + 1) % OPTIONS.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (index - 1 + OPTIONS.length) % OPTIONS.length;
    if (next === null) return;
    e.preventDefault();
    handleToggle(OPTIONS[next].value);
    btnRefs.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label={`Choose how you are using ${BRAND.name}`}
      className={cx(
        'inline-flex rounded-md border border-border bg-bg p-0.5',
        fullWidth && 'flex w-full',
      )}
    >
      {OPTIONS.map((opt, index) => {
        const active = mode === opt.value;
        return (
          <button
            key={opt.value}
            ref={(el) => {
              btnRefs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => handleToggle(opt.value)}
            onKeyDown={(e) => onKeyDown(e, index)}
            className={cx(
              'rounded-[5px] px-3 py-1.5 text-caption font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
              fullWidth && 'flex-1',
              active ? 'bg-primary text-on-primary' : 'text-muted hover:text-text',
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
