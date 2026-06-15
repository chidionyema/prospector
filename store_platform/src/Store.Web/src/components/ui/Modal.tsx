import React, { useEffect, useId, useRef } from 'react';
import { cx } from './cx';
import { Icon } from './Icon';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  /** Optional sticky footer row (e.g. actions). */
  footer?: React.ReactNode;
  /** 'center' = a dialog; 'right' = a slide-in drawer. */
  placement?: 'center' | 'right';
  className?: string;
}

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])';

/**
 * The one dialog/drawer. Inline forms that would otherwise shove page content aside (board "offer an
 * intro", roster edit) move in here so the underlying context stays put (SITE-POLISH-SPEC §2.7).
 * Owns the modal contract: Escape + backdrop close, body-scroll lock, focus moved in on open and
 * restored on close, and Tab trapped within the panel.
 */
export function Modal({ open, onClose, title, children, footer, placement = 'center', className }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const { body } = document;
    const prevOverflow = body.style.overflow;
    body.style.overflow = 'hidden';

    // Move focus into the panel (the first focusable, else the panel itself).
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null,
      );
      if (items.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && active === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && active === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      body.style.overflow = prevOverflow;
      restoreRef.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const isDrawer = placement === 'right';

  return (
    <div className="fixed inset-0 z-50 flex" role="presentation">
      <div
        className="absolute inset-0 bg-text/40 backdrop-blur-sm"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        className={cx(
          'relative flex',
          isDrawer ? 'ml-auto h-full w-full max-w-md' : 'm-auto w-full max-w-lg p-4',
        )}
      >
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          className={cx(
            'flex max-h-full w-full flex-col bg-surface shadow-premium outline-none',
            isDrawer ? 'h-full animate-rise border-l border-border' : 'rounded-lg border border-border animate-rise',
            className,
          )}
        >
          <div className="flex items-center justify-between gap-4 border-b border-border px-6 py-4">
            <h2 id={titleId} className="text-h2 font-semibold text-text">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1.5 text-muted hover:bg-surface2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
            >
              <Icon name="close" size={18} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="border-t border-border px-6 py-4">{footer}</div>}
        </div>
      </div>
    </div>
  );
}
