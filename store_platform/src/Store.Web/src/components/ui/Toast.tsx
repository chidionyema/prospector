import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
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

  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const remainingRef = useRef<Map<string, number>>(new Map());
  const pausedRef = useRef(false);

  const dismiss = useCallback((id: string) => {
    const t = timersRef.current.get(id);
    if (t) clearTimeout(t);
    timersRef.current.delete(id);
    remainingRef.current.delete(id);
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const scheduleDismiss = useCallback((id: string, delayMs: number) => {
    const timer = setTimeout(() => {
      timersRef.current.delete(id);
      remainingRef.current.delete(id);
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, delayMs);
    timersRef.current.set(id, timer);
  }, []);

  const pauseAll = useCallback(() => {
    pausedRef.current = true;
    timersRef.current.forEach((timer, id) => {
      clearTimeout(timer);
      const remaining = remainingRef.current.get(id) ?? 5000;
      remainingRef.current.set(id, remaining);
    });
    timersRef.current.clear();
  }, []);

  const resumeAll = useCallback(() => {
    pausedRef.current = false;
    remainingRef.current.forEach((remaining, id) => {
      scheduleDismiss(id, remaining);
    });
    remainingRef.current.clear();
  }, [scheduleDismiss]);

  const toast = useCallback((message: string, tone: ToastTone = 'info') => {
    const id = crypto.randomUUID();
    setItems((prev) => [...prev, { id, tone, message }]);
    // Auto-dismiss; the screen must still reflect the outcome in its own state.
    scheduleDismiss(id, 5000);
  }, [scheduleDismiss]);

  const api = useMemo<ToastApi>(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-4 right-4 z-60 flex flex-col gap-2"
        onMouseEnter={pauseAll}
        onMouseLeave={resumeAll}
        onFocusCapture={pauseAll}
        onBlurCapture={resumeAll}
      >
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- keyboard reachability per UI polish spec
            tabIndex={0}
            className={cx(
              'pointer-events-auto max-w-sm rounded-md border border-border border-l-2 bg-surface px-4 py-3 text-meta shadow-2',
              TONES[t.tone],
            )}
          >
            <div className="flex items-start gap-3">
              <span className="flex-1">{t.message}</span>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss notification"
                className="text-subtle transition-colors hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
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
