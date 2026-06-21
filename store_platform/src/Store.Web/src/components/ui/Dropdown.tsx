import React from 'react';
import { cx } from './cx';
import { Icon } from './Icon';

export interface DropdownOption<T extends string> {
  value: T;
  label: string;
}

export interface DropdownProps<T extends string> {
  /** Accessible label for the control (announced to screen readers). */
  label: string;
  value: T;
  options: readonly DropdownOption<T>[];
  onChange: (value: T) => void;
  className?: string;
}

/**
 * A headless listbox: a real button that opens a popover of options, with full keyboard
 * support (Arrow/Home/End/Enter/Escape) and `role="listbox"` semantics. Replaces the native
 * <select> so the control is styleable and consistent across every OS, while staying
 * accessible. Closes on outside click and Escape, and returns focus to the trigger.
 */
export function Dropdown<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: DropdownProps<T>) {
  const [open, setOpen] = React.useState(false);
  const [active, setActive] = React.useState(0);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const btnRef = React.useRef<HTMLButtonElement>(null);
  const listRef = React.useRef<HTMLUListElement>(null);
  const labelId = React.useId();

  const selectedIndex = Math.max(0, options.findIndex((o) => o.value === value));
  const current = options[selectedIndex] ?? options[0];

  // Close on outside click.
  React.useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  // When opening, focus the list and highlight the current value.
  React.useEffect(() => {
    if (open) {
      setActive(selectedIndex);
      listRef.current?.focus();
    }
  }, [open, selectedIndex]);

  const choose = (i: number) => {
    onChange(options[i].value);
    setOpen(false);
    btnRef.current?.focus();
  };

  const onListKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setActive((a) => Math.min(a + 1, options.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
        break;
      case 'Home':
        e.preventDefault();
        setActive(0);
        break;
      case 'End':
        e.preventDefault();
        setActive(options.length - 1);
        break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        choose(active);
        break;
      case 'Escape':
        e.preventDefault();
        setOpen(false);
        btnRef.current?.focus();
        break;
      case 'Tab':
        setOpen(false);
        break;
    }
  };

  return (
    <div ref={rootRef} className={cx('relative', className)}>
      <span id={labelId} className="sr-only">
        {label}
      </span>
      <button
        ref={btnRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={labelId}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setOpen(true);
          }
        }}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-white px-3.5 py-2.5 text-sm font-semibold text-text shadow-[0_1px_2px_rgba(0,0,0,0.03)] transition hover:border-text/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-text"
      >
        <span className="truncate">{current?.label}</span>
        <span
          aria-hidden="true"
          className={cx('h-2 w-2 flex-none rotate-45 border-b-2 border-r-2 border-muted transition-transform', open && '-rotate-[135deg]')}
        />
      </button>

      {open && (
        <ul
          ref={listRef}
          role="listbox"
          aria-labelledby={labelId}
          aria-activedescendant={`${labelId}-opt-${active}`}
          tabIndex={-1}
          onKeyDown={onListKeyDown}
          className="absolute z-30 mt-2 w-full overflow-hidden rounded-xl border border-border bg-white p-1 shadow-[0_18px_40px_rgba(0,0,0,0.12)] focus:outline-none"
        >
          {options.map((opt, i) => {
            const selected = opt.value === value;
            return (
              <li
                key={opt.value}
                id={`${labelId}-opt-${i}`}
                role="option"
                aria-selected={selected}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(i)}
                className={cx(
                  'flex cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm font-semibold',
                  i === active ? 'bg-bg text-text' : 'text-text/80',
                )}
              >
                {opt.label}
                {selected && <Icon name="check" size={14} className="text-primary" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
