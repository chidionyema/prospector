import React from 'react';
import { Button } from '@/components/ui';
import { reportClientError } from '@/lib/api/client';

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

/**
 * Top-level client error boundary. A render-time throw anywhere in the tree (a bad API shape, an
 * undefined field) would otherwise blank the whole page to white, for a money surface that reads
 * as "the app is broken, is my hold gone?". This catches it and shows a calm, on-brand recovery
 * panel instead. Class component because React error boundaries have no hook equivalent.
 *
 * Scope: catches render/lifecycle errors only (not event handlers or async, those surface via
 * toasts). Reload is the recovery path; we never expose the raw error to the user.
 *
 * It also REPORTS. Until 2026-08-20 the only trace of a storefront crash was a `console.error` in
 * the buyer's own devtools, which nobody here can read, so the surface where a fault costs money
 * was the one surface the central log could not answer for. `POST /api/client-log` is the
 * server-side hop that puts it in the central log as `svc: "store-web"` -- the browser never
 * talks to the ingest itself, because the ingest is private-network only and its key would end
 * up in client JavaScript.
 */
/**
 * Send the crash to our own server. Fire and forget, and it can never throw: this runs inside a
 * boundary that has already caught one error, and a reporter that throws here would take out the
 * recovery panel and give the buyer the blank white page the boundary exists to prevent.
 *
 * `keepalive` because the most likely next thing the buyer does is reload, and a normal fetch is
 * cancelled by the navigation that follows it.
 */
function report(error: Error, info: React.ErrorInfo): void {
  // The fetch itself lives in lib/api/client.ts. UI-STANDARDS §4 is "components never call fetch
  // directly", eslint enforces it, and an error boundary is a component like any other -- the
  // rule does not get an exception because the caller is unhappy. `reportClientError` swallows
  // every failure for us, which is what this call site needs anyway.
  reportClientError({
    where: 'ErrorBoundary',
    message: String(error?.message || error),
    stack: String(error?.stack || ''),
    componentStack: String(info?.componentStack || ''),
  });
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Still the local console: it is the copy that exists when the report below never lands.
    console.error('Unhandled UI error:', error, info.componentStack);
    report(error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-dvh items-center justify-center bg-bg px-6 font-sans text-text">
          <div className="max-w-md text-center">
            <h1>Something went wrong</h1>
            <p className="mt-3 lede">
              This screen hit an unexpected error. Your account and any funded request are unaffected.
              Reloading usually clears it.
            </p>
            <Button size="lg" className="mt-6" onClick={() => window.location.reload()}>
              Reload the page
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
