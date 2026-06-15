import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { cx } from './cx';

type ToastTone = 'success' | 'info' | 'warning' | 'danger';

interface ToastItem {
  id: string;
  tone: ToastTone;
  message: string;
}

interface ToastApi {
  /** Show a transient notice. NEVER the sole signal for a money outcome (UI-STANDARDS §3). */
  toast: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const TONES: Record<ToastTone, string> = {
  success: 'border-success text-text',
  info: 'border-info text-text',
  warning: 'border-warning text-text',
  danger: 'border-danger text-text',
};

/** Wrap the app once (in `_app`) so any screen can call `useToast()`. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback((message: string, tone: ToastTone = 'info') => {
    const id = crypto.randomUUID();
    setItems((prev) => [...prev, { id, tone, message }]);
    // Auto-dismiss; the screen must still reflect the outcome in its own state.
    setTimeout(() => dismiss(id), 5000);
  }, [dismiss]);

  const api = useMemo<ToastApi>(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cx(
              'pointer-events-auto max-w-sm rounded-md border-l-4 bg-surface px-4 py-3 text-small shadow-2',
              TONES[t.tone],
            )}
          >
            <div className="flex items-start gap-3">
              <span className="flex-1">{t.message}</span>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss notification"
                className="text-muted hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a <ToastProvider>');
  }
  return ctx;
}
