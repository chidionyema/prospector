import React from 'react';

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

/**
 * Top-level client error boundary. A render-time throw anywhere in the tree (a bad API shape, an
 * undefined field) would otherwise blank the whole page to white — for a money surface that reads
 * as "the app is broken, is my hold gone?". This catches it and shows a calm, on-brand recovery
 * panel instead. Class component because React error boundaries have no hook equivalent.
 *
 * Scope: catches render/lifecycle errors only (not event handlers or async — those surface via
 * toasts). Reload is the recovery path; we never expose the raw error to the user.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Surface in the console for now; a real reporter (Sentry) is a deferred, founder-gated decision.
    console.error('Unhandled UI error:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-bg px-6 font-sans text-text">
          <div className="max-w-md text-center">
            <h1 className="text-h2 font-semibold text-text">Something went wrong</h1>
            <p className="mt-3 text-body text-muted">
              This screen hit an unexpected error. Your account and any funded request are unaffected.
              Reloading usually clears it.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-6 inline-flex items-center justify-center rounded-sm bg-primary px-5 py-2.5 text-small font-semibold text-on-primary hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
            >
              Reload the page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
